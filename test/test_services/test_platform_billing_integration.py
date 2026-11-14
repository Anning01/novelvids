import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
import httpx
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
import pytest

from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import BalanceTransaction, Team, TeamMember, User
from config import settings
from models.ai_task import AiTask
from models.chapter import Chapter
from models.config import AiModelConfig
from models.creation_agent import AgentConversation, AgentMessage
from models.novel import Novel
from models.scene import Scene
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from models.video import Video
from schemas.creation_agent import AgentConfiguration
from schemas.platform_billing import PlatformReceiptOut
from services.billing.platform import reconcile_platform_calls, settle_platform_call
from services.creation_agent.handler import configured_model
from services.creation_agent.model_boundary import RecordedAgentModel
from services.platform.access import create_key


@pytest.mark.asyncio
async def test_platform_quota_rejection_is_not_mistaken_for_a_local_balance_failure(monkeypatch):
    from types import SimpleNamespace
    from services.billing.platform import active_model_call, platform_text_client
    from services.creation_agent.handler import public_run_error

    task = await AiTask.create(task_type=7, status=2, request_params={"novel_id": 0})
    config = await AiModelConfig.create(name="额度不足的平台", task_type=7, model="nv-1",
        api_protocol="novelvids", base_url="https://platform.example/v1", api_key="nv_test")
    original = httpx.AsyncClient
    monkeypatch.setattr("services.billing.platform.AsyncClient", lambda **kwargs: original(**{k:v for k,v in kwargs.items() if k != "transport"},
        transport=httpx.MockTransport(lambda _: httpx.Response(402, json={"error": {"code": "insufficient_quota"}}))))
    call = {}
    token = active_model_call.set((SimpleNamespace(task_id=task.id, id=1), call))
    try:
        async with platform_text_client(config) as client:
            response = await client.post(config.base_url + "/chat/completions", json={"model": config.model})
        assert response.status_code == 402
    finally:
        active_model_call.reset(token)
    record = await ModelUsageRecord.get()
    assert record.platform_cost == 0 and record.local_charge == 0
    assert (await StudioCall.get()).state == "rejected"
    assert call["platform_balance_insufficient"]
    from utils.messages import localized_message
    assert public_run_error("provider error", [call]) == localized_message("API 平台账户可用额度不足，请前往 API 平台检查余额和限额")


@pytest.mark.asyncio
async def test_local_settlement_failure_rolls_back_every_write_and_recovers_without_generation(monkeypatch):
    from services.billing.platform import begin_platform_call
    from services.balance import accumulate_member_cost

    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    team = await Team.create(name="事务回滚", balance=10)
    user = await User.create(username="settlement-user")
    member = await TeamMember.create(team=team, user=user, role="creator")
    config = await AiModelConfig.create(name="平台", task_type=7, model="nv-1", api_protocol="novelvids",
        api_key="nv_test", base_url="https://platform.example/v1", pricing={"type": "text", "input_price_per_1m": 30000})
    task = await AiTask.create(task_type=7, status=4, request_params={"novel_id": 0, "team_id": team.id, "user_id": user.id})
    row = await begin_platform_call(config, task_id=task.id, billing_type="text")
    row.platform_request_id = uuid4()
    await row.save(update_fields=["platform_request_id"])
    receipt = PlatformReceiptOut(id=row.platform_request_id, model="nv-1", status="completed", usage={"input_tokens": 10},
        settlement={"status": "settled", "amount": "0.2"}, pricing={})
    monkeypatch.setattr("services.balance.accumulate_member_cost", AsyncMock(side_effect=RuntimeError("storage unavailable")))
    with pytest.raises(RuntimeError):
        await settle_platform_call(row.id, receipt)
    await row.refresh_from_db()
    await team.refresh_from_db()
    ledger = await ModelUsageRecord.get(id=row.usage_record_id)
    assert row.state == "pending" and ledger.platform_cost is None
    assert team.balance == 10 and not await BalanceTransaction.filter(usage_record_id=ledger.id).exists()
    monkeypatch.setattr("services.balance.accumulate_member_cost", accumulate_member_cost)
    await settle_platform_call(row.id, receipt)
    await team.refresh_from_db()
    await member.refresh_from_db()
    assert team.balance == Decimal("9.7") and member.total_cost == Decimal("0.3")
    assert await BalanceTransaction.filter(usage_record_id=ledger.id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "video"])
async def test_media_entrypoints_keep_platform_cost_separate_and_reuse_the_call_record(monkeypatch, kind):
    from services.ai_task_executor import current_task_id
    from services.billing.recorder import billing_recorder, _consume_team_balance
    from services.image_generation.gateway import generate_images
    from services.video import get_generator

    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    team = await Team.create(name="媒体计费", balance=10)
    user = await User.create(username="media-owner")
    await TeamMember.create(team=team, user=user, role="creator")
    novel = await Novel.create(name="媒体项目", team_id=team.id)
    config = await AiModelConfig.create(name="远程媒体", task_type=2 if kind == "image" else 4,
        model="nv-101", api_protocol="novelvids", api_key="nv_test", base_url="https://platform.example/v1",
        image_model_type="gpt_image_2" if kind == "image" else None,
        video_model_type="seedance_2" if kind == "video" else None,
        pricing={"type": "image", "prices": {"1K": .3}} if kind == "image" else
        {"type": "video", "billing_unit": "second", "prices": {"720p": .05}})
    owner = {"novel_id": novel.id, "team_id": team.id, "user_id": user.id, "model_config_id": config.id}
    task = await AiTask.create(task_type=config.task_type, status=2, request_params=owner)
    request_id = uuid4()
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST":
            assert request.headers.get("Idempotency-Key")
            assert "x-team-id" not in request.headers
            result = {"data": [{"url": "https://cdn.example/image.png"}]} if kind == "image" else {"id": "video-job", "status": "queued"}
            return httpx.Response(200, json=result, headers={"X-Cat-Request-Id": str(request_id), "X-Novelvids-Request-Id": str(uuid4()), "X-Request-Id":"supplier-trace"})
        return httpx.Response(200, json={"id": str(request_id), "model": "nv-101", "status": "completed",
            "usage": {"image_count": 1, "clarity": "1K"} if kind == "image" else {"seconds": 6, "resolution": "720p"},
            "settlement": {"status": "settled", "amount": "0.20", "currency": "CNY"}, "pricing": {}})

    original = httpx.AsyncClient
    factory = lambda **kwargs: original(**{k:v for k,v in kwargs.items() if k != "transport"}, transport=httpx.MockTransport(respond))
    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", factory)
    monkeypatch.setattr("services.billing.platform.AsyncClient", factory)
    video = None
    context = current_task_id.set(task.id)
    try:
        if kind == "image":
            result = await generate_images(base_url=config.base_url, api_key=config.api_key, model=config.model,
                prompt="一座山", api_protocol="novelvids", resolution="1K", aspect_ratio="1:1")
            assert result[0].url == "https://cdn.example/image.png"
        else:
            chapter = await Chapter.create(novel=novel, name="第一集", content="正文", number=1)
            scene = await Scene.create(chapter=chapter, sequence=1, prompt="山间")
            video = await Video.create(scene=scene, model_type=1, status=2, metadata=owner)
            result = await get_generator(config).submit(prompt="山间", duration=6, aspect_ratio="16:9", resolution="720p",
                platform_request_key=str(uuid4()), billing_video_id=video.id)
            assert result == "video-job"
    finally:
        current_task_id.reset(context)
    call = await StudioCall.get()
    assert call.platform_request_id == request_id
    await StudioCall.filter(id=call.id).update(next_check_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    await reconcile_platform_calls()
    record = await ModelUsageRecord.get(id=call.usage_record_id)
    assert record.platform_cost == Decimal("0.20") and record.local_charge == Decimal("0.30")
    if kind == "image":
        saved = await billing_recorder.record_image(novel_id=novel.id, task_type=2, model_config_id=config.id,
            ai_task_id=task.id, team_id=team.id, user_id=user.id, image_count=1, clarity="1K")
    else:
        saved = await billing_recorder.record_video(novel_id=novel.id, model_config_id=config.id,
            video_id=video.id, team_id=team.id, user_id=user.id, seconds=6, resolution="720p")
    assert saved.id == record.id
    await _consume_team_balance(saved, team.id, user.id)
    if kind == "image":
        from services.creation_agent.image_settlement import settle_image
        from services.creation_agent.review_evidence import MediaEvidence
        await settle_image(task, {"status": 3}, MediaEvidence("image", quantity=1, completed=True, media_available=True))
    else:
        from services.creation_agent.video_settlement import settle_video
        video.status = 3
        video.metadata = {**video.metadata, "agent_run_id": str(task.id), "provider_accounting": {"status": 3, "seconds": 6}}
        await video.save(update_fields=["status", "metadata"])
        await settle_video(video)
    await record.refresh_from_db()
    assert record.status == 3
    await team.refresh_from_db()
    assert team.balance == Decimal("9.70")
    assert await ModelUsageRecord.all().count() == 1
    assert await BalanceTransaction.filter(usage_record_id=record.id).count() == 1
    assert len([req for req in requests if req.method == "POST"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_text_call_reconciles_actual_cost_and_frozen_local_charge_once(monkeypatch, stream):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    cloud_team = await Team.create(name="平台账户", balance=3)
    cloud_user = await User.create(username="cloud-customer")
    member = await TeamMember.create(team=cloud_team, user=cloud_user, role="creator")
    account = AuthContext(user=cloud_user, team_id=cloud_team.id, membership=member)
    key = (await create_key(account, "部署者自己的 Key"))["key"]
    cloud_model = await AiModelConfig.create(name="平台文本", model="provider-model", task_type=7,
        base_url="https://provider.example/v1", api_key="upstream-secret", is_active=True,
        pricing={"type": "text", "input_price_per_1m": 10, "output_price_per_1m": 20})
    local_team = await Team.create(name="自建团队", balance=2)
    local_user = await User.create(username="local-admin", is_super_admin=True)
    local_member = await TeamMember.create(team=local_team, user=local_user, role="admin")
    local_model = await AiModelConfig.create(name="平台同步模型", model=f"nv-{cloud_model.id}", task_type=7,
        scope="studio_platform", base_url="https://platform.example/v1", api_key=key, api_protocol="novelvids",
        supports_tool_calls=True, is_active=True,
        pricing={"type": "text", "input_price_per_1m": 15, "output_price_per_1m": 40})
    novel = await Novel.create(name="回执闭环", team_id=local_team.id, created_by=local_user.id)
    task = await AiTask.create(task_type=7, status=2, request_params={
        "novel_id": novel.id, "team_id": local_team.id, "user_id": local_user.id})
    conversation = await AgentConversation.create(novel=novel)
    message = await AgentMessage.create(conversation=conversation, task=task, request_id=uuid4(),
        request_hash="test", role="assistant", model_snapshot={"id": local_model.id})
    app = FastAPI()
    app.include_router(developer_router, prefix="/v1")
    original_client = httpx.AsyncClient
    provider_calls = []

    def provider_response(request):
        provider_calls.append(request)
        assert request.headers["Authorization"] == "Bearer upstream-secret"
        if json.loads(request.content).get("stream"):
            common = {"id": "completion", "created": 1, "model": "provider-model", "object": "chat.completion.chunk"}
            chunks = [{**common, "choices": [{"index": 0, "delta": {"content": "生成完成"}, "finish_reason": "stop"}]},
                {**common, "choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}}]
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                text="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n")
        return httpx.Response(200, json={"id": "completion", "created": 1, "model": "provider-model",
            "object": "chat.completion", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "生成完成"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}})

    monkeypatch.setattr("services.platform.chat.provider_client", lambda config: AsyncOpenAI(
        base_url=config.base_url, api_key=config.api_key, max_retries=0,
        http_client=original_client(transport=httpx.MockTransport(provider_response))))

    async def platform_response(request):
        assert "x-team-id" not in request.headers
        if request.url.path.endswith("/chat/completions") and json.loads(request.content).get("stream"):
            assert json.loads(request.content)["stream_options"]["include_usage"] is True
        response = await httpx.ASGITransport(app=app).handle_async_request(request)
        await response.aread()
        return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    def client_factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(platform_response)
        return original_client(**kwargs)

    monkeypatch.setattr("services.billing.platform.AsyncClient", client_factory)
    model = RecordedAgentModel(configured_model(local_model, AgentConfiguration()), message=message,
        before_request=AsyncMock(), max_characters=None)
    messages = [ModelRequest(parts=[UserPromptPart("写一个开场")])]
    if stream:
        async with model.request_stream(messages, None, ModelRequestParameters()) as response:
            async for _ in response:
                pass
            result = response.get()
    else:
        result = await model.request(messages, None, ModelRequestParameters())
    assert result.parts[0].content == "生成完成"
    row = await StudioCall.get()
    ledger = await ModelUsageRecord.get(id=row.usage_record_id)
    assert ledger.cost == 0 and ledger.platform_cost is None and ledger.settlement_status == "pending"
    assert row.local_pricing == local_model.pricing
    assert row.platform_request_id is None  # Legacy platform only sent an unlabelled trace.
    # Each side uses its own price at the time the call was made.
    await AiModelConfig.filter(id=local_model.id).update(pricing={"type": "text", "input_price_per_1m": 100})
    await AiModelConfig.filter(id=cloud_model.id).update(pricing={"type": "text", "input_price_per_1m": 50, "output_price_per_1m": 50})
    # Resolve the legacy unlabelled response from the original idempotency key.
    await StudioCall.filter(id=row.id).update(next_check_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    await reconcile_platform_calls()
    await row.refresh_from_db()
    await ledger.refresh_from_db()
    assert ledger.platform_cost == Decimal("0.012") and ledger.cost == Decimal("0.019")
    assert ledger.local_charge == Decimal("0.019")
    assert ledger.settlement_status == "settled"
    assert ledger.usage["input_tokens"] == 1000
    await cloud_team.refresh_from_db()
    await local_team.refresh_from_db()
    await local_member.refresh_from_db()
    assert cloud_team.balance == Decimal("2.988")
    assert local_team.balance == Decimal("1.981")
    assert local_member.total_cost == ledger.local_charge
    async with original_client(transport=httpx.MockTransport(platform_response)) as client:
        response = await client.get(f"https://platform.example/v1/requests/{row.platform_request_id}",
            headers={"Authorization": f"Bearer {key}"})
    receipt = PlatformReceiptOut.model_validate(response.json())
    await asyncio.gather(settle_platform_call(row.id, receipt), settle_platform_call(row.id, receipt))
    assert await BalanceTransaction.filter(usage_record_id=ledger.id).count() == 1
    assert len(provider_calls) == 1
    from services.balance import top_up
    await top_up(local_team.id, Decimal("1000"), operator_user_id=local_user.id)
    await cloud_team.refresh_from_db()
    assert cloud_team.balance == Decimal("2.988")


def test_billing_upgrade_preserves_legacy_data_and_repeated_startup(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys

    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
        CREATE TABLE general_configs (id INTEGER PRIMARY KEY, prompt_language TEXT);
        INSERT INTO general_configs VALUES (1, 'zh');
        CREATE TABLE model_usage_records (id INTEGER PRIMARY KEY, cost DECIMAL);
        INSERT INTO model_usage_records VALUES (1, 2.5);
        CREATE TABLE platformcallreceipt (id INTEGER PRIMARY KEY);
        """)
    script = """
import asyncio
from tortoise import Tortoise
from services.schema_compat import ensure_billing_integration_schema
import models
async def main():
    await Tortoise.init(db_url='sqlite://'+__import__('os').environ['BILLING_TEST_DB'], modules={'models':[f'models.{name}' for name in models.__all__]})
    await ensure_billing_integration_schema()
    await ensure_billing_integration_schema()
    await Tortoise.close_connections()
asyncio.run(main())
"""
    subprocess.run([sys.executable, "-c", script], check=True, env={**os.environ, "BILLING_TEST_DB": str(db)})
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT prompt_language FROM general_configs").fetchone() == ("zh",)
        assert connection.execute("SELECT cost,platform_cost,local_charge,settlement_status FROM model_usage_records").fetchone() == (2.5, None, None, "legacy")


@pytest.mark.asyncio
async def test_pixel_receipt_reviews_incomplete_usage_then_settles_frozen_price_once(monkeypatch):
    from services.billing.platform import begin_platform_call

    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    team = await Team.create(name="像素分档", balance=1)
    user = await User.create(username="pixel-owner")
    await TeamMember.create(team=team, user=user, role="creator")
    tariff = {"type": "image", "billing_unit": "pixel_tier", "prices": {"low": .13, "high_capped": .23},
              "input_image": {"first_free": 0, "price_per_image": .05}}
    config = await AiModelConfig.create(name="5.5", task_type=2, model="nv-55", api_protocol="novelvids",
        api_key="nv_test", base_url="https://platform.example/v1", pricing=tariff, image_model_type="seedream_5_5")
    task = await AiTask.create(task_type=2, request_params={"team_id": team.id, "user_id": user.id})
    call = await begin_platform_call(config, task_id=task.id, billing_type="image")
    call.platform_request_id = uuid4()
    await call.save(update_fields=["platform_request_id"])
    await AiModelConfig.filter(id=config.id).update(pricing={**tariff, "discount": 0.5})
    receipt = PlatformReceiptOut(id=call.platform_request_id, model=config.model, status="completed",
        usage={"image_count": 1, "input_image_count": 2}, settlement={"status": "settled", "amount": ".2"}, pricing={})
    await settle_platform_call(call.id, receipt)
    ledger = await ModelUsageRecord.get(id=call.usage_record_id)
    assert ledger.settlement_status == "review" and not await BalanceTransaction.filter(usage_record_id=ledger.id).exists()
    receipt.usage["output_tier_counts"] = {"high_capped": 1}
    await settle_platform_call(call.id, receipt)
    await settle_platform_call(call.id, receipt)
    await ledger.refresh_from_db()
    assert ledger.platform_cost == Decimal(".2") and ledger.local_charge == Decimal(".33")
    assert await BalanceTransaction.filter(usage_record_id=ledger.id).count() == 1
