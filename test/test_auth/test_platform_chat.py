import asyncio
import json
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI

from api.platform import developer_router
from auth.models import BalanceTransaction, PlatformCallReceipt, Team, TeamMember, User
from auth.deps import AuthContext
from config import settings
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.platform.access import create_key, revoke_key
from services.platform.calls import recover_measured

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires authenticated platform")


@pytest.fixture
async def setup_call(monkeypatch):
    team = await Team.create(name="平台请求", balance=3)
    user = await User.create(username="platform-model-user",password_hash="!")
    member = await TeamMember.create(team=team,user=user,role="creator")
    model = await AiModelConfig.create(name="平台文本",model="upstream-model",base_url="https://example.invalid/v1",
        task_type=7,api_key="provider-test",supports_tool_calls=True,is_active=True,pricing={"type":"text","input_price_per_1m":10,
        "cache_input_price_per_1m":1,"output_price_per_1m":20})
    key = (await create_key(AuthContext(user=user,membership=member,team_id=team.id),"studio"))["key"]
    app = FastAPI()
    app.include_router(developer_router,prefix="/v1")
    sent = []
    def respond(request):
        req = json.loads(request.content)
        sent.append(req)
        assert request.headers['authorization']=='Bearer provider-test' and req["model"]=="upstream-model"
        envelope = {"id":"chatcmpl-1","created":1,"model":"upstream-model"}
        usage = {"prompt_tokens":1000,"completion_tokens":100,"total_tokens":1100,"prompt_tokens_details":{"cached_tokens":200}}
        if req["stream"]:
            assert req['stream_options']=={'include_usage':True}
            chunks = [{**envelope,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"猫影"},"finish_reason":"stop"}]},
                      {**envelope,"object":"chat.completion.chunk","choices":[],"usage":usage}]
            return httpx.Response(200,headers={"Content-Type":"text/event-stream"},text="".join("data: "+json.dumps(c)+"\n\n" for c in chunks)+"data: [DONE]\n\n")
        return httpx.Response(200,json={**envelope,"object":"chat.completion",
            "choices":[{"index":0,"message":{"role":"assistant","content":"猫影"},"finish_reason":"stop"}],"usage":usage})
    monkeypatch.setattr("services.platform.chat.provider_client",lambda cfg: AsyncOpenAI(base_url=cfg.base_url,api_key=cfg.api_key,
        max_retries=0,http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://platform") as http:
        yield http, {"Authorization":"Bearer "+key}, f"nv-{model.id}", sent, team, member


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_public_chat_routes_selected_model_and_charges_actual_usage_once(setup_call,stream):
    http,headers,model,sent,team,member=setup_call
    headers={**headers,"Idempotency-Key":"my-generation"}
    data={"model":model,"stream":stream,"messages":[{"role":"user","content":"写一个开场"}],
          "tools":[{"type":"function","function":{"name":"read_scene","parameters":{"type":"object"}}}]}
    if stream: data["stream_options"]={"include_usage":True}
    reply=await http.post("/v1/chat/completions",headers=headers,json=data)
    assert reply.status_code==200, reply.text
    assert "upstream-model" not in reply.text and model in reply.text
    if stream:
        assert "data: [DONE]" in reply.text and '"completion_tokens": 100' in reply.text
    else:
        assert reply.json()["choices"][0]["message"]["content"]=="猫影"
    duplicate=await http.post("/v1/chat/completions",headers=headers,json=data)
    assert duplicate.status_code==409 and len(sent)==1 and sent[0]["tools"]==data["tools"]
    assert duplicate.headers["X-Request-Id"]==reply.headers["X-Request-Id"]
    status=await http.get("/v1/requests/"+reply.headers["X-Request-Id"],headers=headers)
    assert status.json()["status"]=="completed" and status.json()["usage"]["cache_read_tokens"]==200
    assert status.json()["settlement"] == {"status": "settled", "amount": "0.010200", "currency": "CNY"}
    assert status.headers["Cache-Control"] == "no-store"
    recovered = await http.get('/v1/requests', params={'request_key': 'my-generation'}, headers=headers)
    assert recovered.json() == status.json()
    assert "provider-test" not in status.text and "upstream-model" not in status.text
    assert (await PlatformCallReceipt.get()).api_key_id is not None
    usage=await ModelUsageRecord.get()
    assert usage.novel_id==0 and usage.cost==Decimal(".0102") and usage.team_id==team.id
    await team.refresh_from_db()
    await member.refresh_from_db()
    assert team.balance==Decimal("2.9898") and member.total_cost==usage.cost
    assert await BalanceTransaction.filter(usage_record_id=usage.id).count()==1


@pytest.mark.asyncio
async def test_receipts_follow_platform_account_and_allow_authorized_key_rotation(setup_call):
    from auth.models import PlatformApiKey
    http, headers, model, sent, team, member = setup_call
    response = await http.post('/v1/chat/completions', headers=headers,
        json={'model': model, 'messages': [{'role': 'user', 'content': 'test'}]})
    path = '/v1/requests/' + response.headers['X-Request-Id']
    user = await User.get(id=member.user_id)
    owner = AuthContext(user=user, team_id=team.id, membership=member)
    previous = await PlatformApiKey.get(team_id=team.id, user_id=user.id)
    fresh = (await create_key(owner, '更换 Key'))['key']
    await revoke_key(owner, previous.id)
    assert (await http.get(path, headers=headers)).status_code == 401
    own = await http.get(path, headers={'Authorization': 'Bearer ' + fresh, 'X-Team-Id': '999999'})
    assert own.status_code == 200 and own.json()['settlement']['amount'] == '0.010200'
    foreign_team = await Team.create(name='另一平台账户', balance=50)
    foreign_user = await User.create(username='other-receipt-user', is_super_admin=True)
    foreign_member = await TeamMember.create(team=foreign_team, user=foreign_user, role='admin')
    foreign_key = (await create_key(AuthContext(user=foreign_user, team_id=foreign_team.id,
        membership=foreign_member), '另一账户 Key'))['key']
    denied = await http.get(path, headers={'Authorization': 'Bearer ' + foreign_key, 'X-Team-Id': str(team.id)})
    assert denied.status_code == 404 and '0.010200' not in denied.text
    account = await http.get('/v1/account', headers={'Authorization': 'Bearer ' + fresh})
    assert Decimal(account.json()['balance']) == Decimal('2.9898')
    assert account.json()['recharge_url'].endswith(f'/#/profile?recharge=1&team={team.id}')
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_no_upstream_call_on_insufficient_balance_or_non_public_model(setup_call):
    http,h,model,sent,team,member=setup_call
    body={"model":model,"messages":[{"role":"user","content":"test"}]}
    await TeamMember.filter(id=member.id).update(cost_limit=0)
    assert (await http.post("/v1/chat/completions",headers=h,json=body)).status_code==402
    await TeamMember.filter(id=member.id).update(cost_limit=None)
    await Team.filter(id=team.id).update(balance=0)
    assert (await http.post("/v1/chat/completions",headers=h,json=body)).status_code==402
    assert (await http.post("/v1/chat/completions",headers=h,json={**body,"model":"nv-999999"})).status_code==404
    assert not sent and not await PlatformCallReceipt.all().exists()


@pytest.mark.asyncio
async def test_failed_debit_can_be_retried_without_regenerating_or_partial_charge(setup_call,monkeypatch):
    from services.platform import calls
    http,h,model,sent,team,_=setup_call
    debit=calls.consume
    async def unavailable(*args,**kwargs): raise RuntimeError("test fault")
    monkeypatch.setattr(calls,"consume",unavailable)
    result=await http.post("/v1/chat/completions",headers=h,json={"model":model,"messages":[{"role":"user","content":"test"}]})
    assert result.status_code==502 and (await PlatformCallReceipt.get()).state=="measured"
    assert not await ModelUsageRecord.all().exists() and not await BalanceTransaction.all().exists()
    monkeypatch.setattr(calls,"consume",debit)
    await asyncio.gather(recover_measured(), recover_measured())
    assert len(sent)==1 and await BalanceTransaction.all().count()==1 and (await PlatformCallReceipt.get()).state=="completed"


@pytest.mark.asyncio
async def test_local_sdk_can_stream_with_the_public_base_url(setup_call):
    http,headers,model,sent,_,_=setup_call
    studio = AsyncOpenAI(api_key=headers["Authorization"].split()[1], base_url="http://platform/v1",
                         http_client=http, max_retries=0)
    reply = await studio.chat.completions.create(model=model, messages=[{"role":"user","content":"test"}], stream=True)
    chunks = [part async for part in reply]
    assert [c.choices[0].delta.content for c in chunks] == ["猫影"]
    assert sent[0]["stream_options"] == {"include_usage":True}
    assert (await PlatformCallReceipt.get()).state == "completed"


@pytest.mark.asyncio
async def test_disconnect_still_collects_last_upstream_usage(setup_call):
    from types import SimpleNamespace
    from starlette.requests import ClientDisconnect
    from services.platform.calls import admit
    from services.platform.chat import ChatStream
    from unittest.mock import AsyncMock

    _,_,model,_,team,member=setup_call
    _,receipt = await admit(AuthContext(team_id=team.id,user=await member.user, membership=member),int(model[3:]),{},"disconnect")
    release = asyncio.Event()
    class Chunk:
        id = "upstream-stream"
        choices = [{"delta":{"content":"text"}}]
        usage = None
        def model_dump(self, **kwargs):
            return {"id":self.id, "choices": self.choices}
    async def chunks():
        first=Chunk()
        yield first
        await release.wait()
        last=Chunk()
        last.choices=[]
        last.usage=SimpleNamespace(prompt_tokens=10,completion_tokens=5)
        yield last
    client=AsyncMock()
    response=ChatStream(client,chunks(),receipt,model,False,asyncio.get_running_loop().time()+5)
    async def send(event):
        if event["type"]=="http.response.body": raise OSError("peer disconnected")
    with pytest.raises(ClientDisconnect):
        await response({"type":"http","asgi":{"spec_version":"2.4"}},AsyncMock(),send)
    release.set()
    from services.platform.chat import stop_streams
    await stop_streams()
    await receipt.refresh_from_db()
    assert receipt.state=="completed" and receipt.usage["output_tokens"]==5
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_usage_kept_for_review_without_inventing_a_fee(setup_call,monkeypatch):
    http,h,model,_,_,_=setup_call
    def incomplete(request):
        return httpx.Response(200,json={"id":"missing","object":"chat.completion","created":1,"model":"upstream",
                                       "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"answer"}}]})
    monkeypatch.setattr("services.platform.chat.provider_client",lambda _:AsyncOpenAI(base_url="https://example.invalid/v1",
        api_key="test",http_client=httpx.AsyncClient(transport=httpx.MockTransport(incomplete)),max_retries=0))
    reply=await http.post("/v1/chat/completions",headers=h,json={"model":model,"messages":[{"role":"user","content":"test"}]})
    row = await PlatformCallReceipt.get()
    assert reply.status_code==502 and row.state=="review" and row.provider_id=="missing"
    assert not await ModelUsageRecord.all().exists()


@pytest.mark.asyncio
async def test_local_studio_structured_output_and_concurrent_retry_use_frozen_price(setup_call, monkeypatch):
    from pydantic import BaseModel
    from services.llm.json_output import create_json_completion
    http,headers,model,_,_,_=setup_call
    started, release = asyncio.Event(), asyncio.Event()
    submitted = []
    async def reply(request):
        body=json.loads(request.content)
        submitted.append(body)
        started.set()
        await release.wait()
        return httpx.Response(200,json={"id":"existing","object":"chat.completion","model":"upstream-model","created":1,
            "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":json.dumps({"episode":1})}}],
            "usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}})
    monkeypatch.setattr("services.platform.chat.provider_client", lambda cfg: AsyncOpenAI(api_key=cfg.api_key,base_url=cfg.base_url,
        max_retries=0,http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply))))
    await AiModelConfig.filter(id=int(model[3:])).update(supports_json_output=True)
    studio=AsyncOpenAI(api_key=headers["Authorization"].split()[1],base_url="http://platform/v1",http_client=http,
                       default_headers={"Idempotency-Key":"studio-retry"},max_retries=0)
    class Episode(BaseModel):
        episode:int
    async def run():
        return await create_json_completion(studio,model=model,response_model=Episode,messages=[{"role":"user","content":"第一集"}],
                                            supports_json_output=True)
    original=asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(),3)
        from openai import ConflictError
        with pytest.raises(ConflictError): await run()
        saturated=await http.post("/v1/chat/completions",headers=headers,json={"model":model,"messages":[{"role":"user","content":"other"}]})
        assert saturated.status_code==429
        await AiModelConfig.filter(id=int(model[3:])).update(pricing={"type":"text","input_price_per_1m":100,"output_price_per_1m":100})
    finally:
        release.set()
    result,_=await original
    assert result.episode==1 and len(submitted)==1 and submitted[0]["response_format"]=={"type":"json_object"}
    assert (await ModelUsageRecord.get()).cost==Decimal(".002")
