import base64
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
import wave

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import BalanceTransaction, Team, TeamMember, User
from config import settings
from controllers.config import ai_model_config_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.config import AiModelConfig
from models.novel import Novel
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from prompts.voice_design import render_voice_design
from schemas.config import AiModelConfigCreate
from schemas.media_library import AudioReferenceAutoDesignIn
from schemas.platform_billing import PlatformReceiptOut
from services import voice_design
from services.billing.platform import settle_platform_call
from services.platform.access import create_key
from services.platform.catalog import model_catalog
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


VOICE_PRICE = {"type": "voice_design", "billing_unit": "second", "price_per_second": .1}
TEXT_PRICE = {"type": "text", "input_price_per_1m": 1, "output_price_per_1m": 2}


def wav(seconds=3):
    output = BytesIO()
    with wave.open(output, "wb") as file:
        file.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
        file.writeframes(bytes(2 * 24_000 * seconds))
    return output.getvalue()


def voice_response(data):
    return {"id": "voice-provider-id", "choices": [{"message": {
        "role": "assistant", "content": None, "audio": {"data": base64.b64encode(data).decode()},
    }}]}


def text_response():
    return {"id": "text-provider-id", "created": 1, "object": "chat.completion", "model": "text",
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
                         "content": '{"voice_description":"平和低沉","sample_text":"我们慢慢谈。","gender":"male"}'}}]}


def mock_provider(monkeypatch, respond):
    original = httpx.AsyncClient

    class MockedClient(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", MockedClient)


async def make_context(monkeypatch, name):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    team = await Team.create(name=f"{name}-team", balance=10)
    user = await User.create(username=f"{name}-creator")
    membership = await TeamMember.create(team=team, user=user, role="creator")
    return AuthContext(user=user, membership=membership, team_id=team.id), team


async def make_project(team_id):
    project = await Novel.create(name="音色项目", team_id=team_id)
    asset = await Asset.create(novel_id=project.id, asset_type=AssetTypeEnum.person.value,
                               canonical_name="角色", metadata={"gender": "男", "voice": "原音色", "voice_reference_id": 21})
    form = await AssetVariant.create(asset_id=asset.id, name="青年", metadata={"editor_form": {"age_group": "青年"}})
    return project, asset, form


async def config(name, task_type, *, protocol="openai_compatible", pricing=None):
    return await ai_model_config_controller.create(AiModelConfigCreate(
        name=name, task_type=task_type, base_url=f"https://{name}.example/v1", api_key="provider-test",
        model="mimo-v2.5-tts-voicedesign" if task_type == AiTaskTypeEnum.voice_design else name,
        is_active=True, api_protocol=protocol, pricing=pricing,
    ))


@pytest.mark.asyncio
async def test_designs_variant_uses_real_wav_and_bills_both_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(voice_design, "oss", SimpleNamespace(enabled=False))
    ctx, team = await make_context(monkeypatch, "variant")
    project, asset, form = await make_project(team.id)
    await config("text", AiTaskTypeEnum.project_analysis, pricing=TEXT_PRICE)
    await config("voice", AiTaskTypeEnum.voice_design, protocol="mimo_voice_design", pricing=VOICE_PRICE)
    data = wav()
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        if request.url.host == "text.example":
            assert body["messages"][0]["role"] in {"system", "developer"}
            assert "青年" in body["messages"][-1]["content"]
            return httpx.Response(200, json=text_response())
        assert request.headers["api-key"] == "provider-test"
        assert "authorization" not in request.headers
        assert request.url.path == "/v1/chat/completions"
        assert body["model"] == "mimo-v2.5-tts-voicedesign"
        assert body["messages"] == [{"role": "user", "content": "平和低沉"},
                                    {"role": "assistant", "content": "我们慢慢谈。"}]
        return httpx.Response(200, json=voice_response(data))

    mock_provider(monkeypatch, respond)
    reference, metadata = await voice_design.auto_design_voice_for_asset(
        AudioReferenceAutoDesignIn(asset_id=asset.id, variant_id=form.id, expected_voice_reference_id=None), ctx,
    )
    await asset.refresh_from_db()
    await form.refresh_from_db()
    await team.refresh_from_db()
    assert asset.metadata["voice_reference_id"] == 21
    assert form.metadata == metadata
    assert metadata["editor_form"]["voice_reference_id"] == reference.id
    assert metadata["editor_form"]["age_group"] == "青年"
    assert reference.duration == 3 and reference.team_id == team.id
    assert (tmp_path / reference.audio_url.removeprefix("/media/")).read_bytes() == data
    usage = {row.billing_type: row for row in await ModelUsageRecord.filter(novel_id=project.id)}
    assert usage["voice_design"].usage == {"seconds": 3}
    assert usage["voice_design"].cost == Decimal("0.3")
    assert usage["text"].cost == Decimal("0.000160")
    assert team.balance == Decimal("9.699840")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_voice_change_during_upload_keeps_latest_binding_and_cleans_sample(monkeypatch, tmp_path):
    ctx, team = await make_context(monkeypatch, "race")
    project, asset, form = await make_project(team.id)
    path = tmp_path / "sample.wav"
    path.write_bytes(wav())

    async def upload(*_):
        form.metadata = {"voice": "用户刚选的音色", "voice_reference_id": 22}
        await form.save(update_fields=["metadata"])

    delete = AsyncMock()
    monkeypatch.setattr(voice_design, "oss", SimpleNamespace(enabled=True, put_file=upload, delete=delete))
    payload = AudioReferenceAutoDesignIn(asset_id=asset.id, variant_id=form.id, expected_voice_reference_id=None)
    draft = voice_design.VoiceDesignDraft(voice_description="低音", sample_text="你好。", gender="male")
    with pytest.raises(HTTPException) as failure:
        await voice_design._bind_sample(payload, ctx, project, path, 3, draft)
    assert failure.value.status_code == 409
    assert not await AudioReference.exists()
    assert (await AssetVariant.get(id=form.id)).metadata["voice_reference_id"] == 22
    delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_failure_rolls_back_audio_row_and_removes_local_file(monkeypatch, tmp_path):
    ctx, team = await make_context(monkeypatch, "rollback")
    project, asset, _ = await make_project(team.id)
    monkeypatch.setattr(voice_design, "oss", SimpleNamespace(enabled=False))
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(Asset, "save", AsyncMock(side_effect=RuntimeError("database failure")))
    path = tmp_path / "sample.wav"
    path.write_bytes(wav())
    request = AudioReferenceAutoDesignIn(asset_id=asset.id, expected_voice_reference_id=21, expected_voice="原音色")
    draft = voice_design.VoiceDesignDraft(voice_description="低音", sample_text="你好。", gender="male")
    with pytest.raises(RuntimeError, match="database failure"):
        await voice_design._bind_sample(request, ctx, project, path, 3, draft)
    assert not await AudioReference.exists()
    assert (await Asset.get(id=asset.id)).metadata["voice_reference_id"] == 21
    assert not list((tmp_path / "audio-references").iterdir())


@pytest.mark.asyncio
async def test_blank_expected_binding_does_not_replace_existing_voice(monkeypatch):
    ctx, team = await make_context(monkeypatch, "replace")
    _, asset, _ = await make_project(team.id)
    with pytest.raises(HTTPException) as failure:
        await voice_design.auto_design_voice_for_asset(
            AudioReferenceAutoDesignIn(asset_id=asset.id, expected_voice_reference_id=None), ctx,
        )
    assert failure.value.status_code == 409
    assert not await ModelUsageRecord.exists()


@pytest.mark.asyncio
async def test_project_write_access_is_checked_before_model_access(monkeypatch):
    ctx, team = await make_context(monkeypatch, "scope")
    project, asset, _ = await make_project(team.id)
    check = AsyncMock(side_effect=HTTPException(404))
    config_access = AsyncMock()
    monkeypatch.setattr(voice_design, "ensure_novel_access", check)
    monkeypatch.setattr(ai_model_config_controller, "get_active", config_access)
    request = AudioReferenceAutoDesignIn(asset_id=asset.id, expected_voice_reference_id=21, expected_voice="原音色")
    with pytest.raises(HTTPException) as failure:
        await voice_design.auto_design_voice_for_asset(request, ctx)
    assert failure.value.status_code == 404
    check.assert_awaited_once_with(project.id, ctx)
    config_access.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("pricing", [None, {**VOICE_PRICE, "price_per_second": -1}, {**VOICE_PRICE, "billing_unit": "minute"}])
async def test_voice_config_requires_an_explicit_valid_tariff(pricing):
    with pytest.raises(HTTPException) as error:
        await config("voice", AiTaskTypeEnum.voice_design, protocol="mimo_voice_design", pricing=pricing)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_public_voice_protocol_catalog_dedup_and_studio_settlement(monkeypatch):
    ctx, team = await make_context(monkeypatch, "platform")
    key = await create_key(ctx, "voice", studio=True)
    provider = await config("voice", AiTaskTypeEnum.voice_design, protocol="mimo_voice_design", pricing=VOICE_PRICE)
    listed, = await model_catalog()
    assert listed["task_types"] == [AiTaskTypeEnum.voice_design]
    assert listed["pricing"]["price_per_second"] == .1
    app = FastAPI()
    app.include_router(developer_router, prefix="/v1")
    called = []
    data = wav(32)
    def respond(request):
        called.append(request)
        return httpx.Response(200, json=voice_response(data))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://platform.test") as client:
        mock_provider(monkeypatch, respond)
        headers = {"Authorization": f"Bearer {key['key']}", "Idempotency-Key": str(uuid4())}
        payload = {"model": listed["id"], "audio": {"format": "wav"}, "stream": False,
                   "messages": [{"role": "user", "content": "沉稳"}, {"role": "assistant", "content": "台词"}]}
        response = await client.post("/v1/chat/completions", json=payload, headers=headers)
        assert response.status_code == 200, response.text[:1000]
        assert response.json()["model"] == listed["id"]
        assert base64.b64decode(response.json()["choices"][0]["message"]["audio"]["data"]) == data
        replay = await client.post("/v1/chat/completions", json=payload, headers=headers)
        assert replay.status_code == 409
        assert len(called) == 1
        receipt = await client.get("/v1/requests/" + response.headers["X-Request-Id"], headers=headers)
        assert receipt.json()["usage"] == {"seconds": 32}
        assert Decimal(receipt.json()["settlement"]["amount"]) == Decimal("3.2")
    await team.refresh_from_db()
    assert team.balance == Decimal("6.8")
    assert await BalanceTransaction.filter(team_id=team.id).count() == 1

    project = await Novel.create(name="工作台项目", team_id=team.id)
    synced = await AiModelConfig.create(name="synced-voice", task_type=AiTaskTypeEnum.voice_design, api_protocol="novelvids",
        base_url="https://platform.test/v1", model=f"nv-{provider.id}", api_key="studio-test",
        pricing={**VOICE_PRICE, "price_per_second": .02})
    from services.billing.voice_design import run_voice_model
    receipt_id = UUID(receipt.json()["id"])

    def respond_studio(request):
        assert request.headers.get("Idempotency-Key")
        return httpx.Response(200, json=voice_response(data), headers={"X-Cat-Request-Id": str(receipt_id)})

    monkeypatch.undo()
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    mock_provider(monkeypatch, respond_studio)

    async def execute(client):
        await client.post(synced.base_url + "/chat/completions")
        return None, {"seconds": 32}

    await run_voice_model(synced, project=project, user_id=ctx.user.id, kind="voice_design", execute=execute)
    studio = await StudioCall.get(model_config_id=synced.id)
    evidence = PlatformReceiptOut.model_validate(receipt.json())
    await settle_platform_call(studio.id, evidence)
    await settle_platform_call(studio.id, evidence)
    row = await ModelUsageRecord.get(id=studio.usage_record_id)
    assert row.platform_cost == Decimal("3.2")
    assert row.local_charge == Decimal(".64")
    assert await BalanceTransaction.filter(usage_record_id=row.id).count() == 1


@pytest.mark.parametrize("language, expected", [("en", "short English"), ("zh", "中文台词")])
def test_voice_prompt_keeps_facts_separate_and_uses_project_language(language, expected):
    system, user = render_voice_design({"name": "阿宁"}, language)
    assert expected in system
    assert "阿宁" not in system
    assert json.loads(user) == {"name": "阿宁"}
