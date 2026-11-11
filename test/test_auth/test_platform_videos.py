import asyncio
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import BalanceTransaction, PlatformCallReceipt, PlatformVideoJob, Team, TeamMember, User
from config import settings
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.platform.access import create_key
from services.platform.videos import measured, video_cost
from utils.enums import TaskStatusEnum
from services.video import get_generator

pytestmark=pytest.mark.skipif(not settings.AUTH_ENABLED,reason="requires platform authentication")


@pytest.fixture
async def video_api():
    user=await User.create(username="video-api-author",password_hash="!")
    team=await Team.create(name="视频调用",balance=10)
    member=await TeamMember.create(user=user,team=team,role="creator")
    key=(await create_key(AuthContext(user=user,team_id=team.id,membership=member),"studio",studio=True))["key"]
    model=await AiModelConfig.create(name="公开视频",model="vendor-video",task_type=4,is_active=True,
        video_model_type="seedance_2_5",api_protocol="volcengine_ark",api_key="test-vendor",base_url="https://vendor.example/api/v3",
        pricing={"type":"video","prices":{"720p":40},"video_reference_prices":{"720p":30},"discount":0.5})
    local=await AiModelConfig.create(name="本地平台视频",model=f"nv-{model.id}",task_type=4,is_active=True,team_id=team.id,scope="team",
        video_model_type="seedance_2_5",api_protocol="novelvids",api_key=key,base_url="https://platform.example/v1")
    app=FastAPI()
    app.include_router(developer_router,prefix="/v1")
    return app,key,model,team,local


async def test_studio_video_job_survives_disconnect_and_settles_once(video_api,monkeypatch,tmp_path):
    from controllers.video import _download_video
    from services.platform.videos import refresh_job
    from services.video.poster import video_poster_service
    from unittest.mock import AsyncMock
    app,key,model,team,local=video_api
    backend=httpx.ASGITransport(app=app)
    client_type=httpx.AsyncClient
    posts=[]
    cloud_queries=[]
    result_files=[]
    request_key=uuid4()
    async def dispatch(req):
        if req.url.host=="platform.example":
            assert req.headers["Authorization"]=="Bearer "+key
            reply=await backend.handle_async_request(req)
            if req.method=="POST":
                # Upstream accepted. The studio loses the HTTP response but retains its request ID.
                assert reply.status_code==200, await reply.aread()
                raise httpx.ReadError("test disconnect",request=req)
            return reply
        if req.url.host=="vendor.example":
            assert req.headers["Authorization"]=="Bearer test-vendor"
            if req.method=="POST":
                body=json.loads(req.content);posts.append(body)
                assert body["model"]=="vendor-video"
                assert body["content"][1]["image_url"]["url"]=="https://images.example/shot.png"
                assert "图片1" in body["content"][0]["text"]
                return httpx.Response(200,json={"id":"accepted-video"})
            cloud_queries.append(req.url.path)
            return httpx.Response(200,json={"status":"succeeded","content":{"video_url":"https://cdn.example/result.mp4"},
                "duration":5,"usage":{"completion_tokens":10000}})
        assert req.url.host=="cdn.example" and req.method=="GET" and "authorization" not in req.headers
        result_files.append(req.url.path)
        return httpx.Response(200,content=b"direct video bytes")
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:client_type(**kw,transport=httpx.MockTransport(dispatch)))
    gen=get_generator(local)
    handle=await gen.submit("参考 @图片1",duration=5,resolution="720p",aspect_ratio="16:9",
        reference_images=["https://images.example/shot.png"],platform_request_key=request_key)
    assert handle=="req-"+str(request_key)
    receipt=await PlatformCallReceipt.get()
    job=await PlatformVideoJob.get(receipt_id=receipt.id)
    assert receipt.state=="processing" and not result_files
    # A background worker can finish billing without a connected client.
    await asyncio.gather(refresh_job(job,receipt), refresh_job(job,receipt))
    assert len(cloud_queries)==1 and not result_files
    finished=await get_generator(local).query(handle)
    assert finished["status"]==3 and finished["url"]=="https://cdn.example/result.mp4"
    assert (await get_generator(local).query(handle))["status"]==3
    assert len(posts)==len(cloud_queries)==1
    usage=await ModelUsageRecord.get()
    assert usage.cost==Decimal(".2") and usage.billing_type=="video" and usage.usage["video_tokens"]==10000
    assert await BalanceTransaction.filter(usage_record_id=usage.id).count()==1
    await team.refresh_from_db();assert team.balance==Decimal("9.8")
    monkeypatch.setattr(settings,"MEDIA_PATH",str(tmp_path))
    monkeypatch.setattr(video_poster_service,"extract_file_and_store",AsyncMock(return_value={}))
    monkeypatch.setattr("services.video.duration.measure_video_duration",lambda _:5.0)
    from types import SimpleNamespace
    monkeypatch.setattr("services.oss.oss",SimpleNamespace(enabled=True))
    path,_=await _download_video(finished["url"],1234,keep_local=True)
    assert (tmp_path/path.removeprefix("/media/")).read_bytes()==b"direct video bytes"
    assert result_files==["/result.mp4"]
    await PlatformVideoJob.filter(id=job.id).update(poll_after=0)
    renewed=await get_generator(local).query(handle, refresh=True)
    assert renewed["url"]==finished["url"] and len(cloud_queries)==2
    assert len(posts)==1 and await BalanceTransaction.filter(usage_record_id=usage.id).count()==1


async def test_public_video_rejects_foreign_receipt_and_bad_inputs(video_api):
    app,key,model,team,local=video_api
    other=await User.create(username="another-video-user",password_hash="!")
    membership=await TeamMember.create(team=team,user=other,role="creator")
    foreign=(await create_key(AuthContext(user=other,team_id=team.id,membership=membership),"external"))["key"]
    public=uuid4()
    receipt=await PlatformCallReceipt.create(public_id=public,dedup_key="reserved",payload_hash="123",team_id=team.id,
        user_id=membership.user_id,model_config_id=model.id,model=model.model,model_name=model.name,pricing=model.pricing)
    await PlatformVideoJob.create(receipt=receipt,route_hash="test",inputs={})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        headers={"Authorization":"Bearer "+key}
        assert (await c.get("/v1/videos/"+str(public),headers=headers)).status_code==404
        assert (await c.get("/v1/videos/"+str(public),headers={"Authorization":"Bearer "+foreign})).status_code==200
        base={"model":local.model,"prompt":"test","duration":5,"aspect_ratio":"16:9","resolution":"720p"}
        for refs in [[{"type":"image","url":"data:image/png;base64,xyz"}],
                     [{"type":"video","url":"https://example.com/video.mp4","role":"first_frame"}]]:
            assert (await c.post("/v1/videos",headers=headers,json={**base,"references":refs})).status_code==422
        assert not await ModelUsageRecord.all().exists()


def test_video_seconds_use_verified_input_and_output_or_leave_pending():
    inputs={"duration":15,"resolution":"720p","input_image_count":0,"has_video_reference":True}
    rates={"type":"video","billing_unit":"second","prices":{"720p":1},"video_reference_prices":{"720p":0.5}}
    assert measured(inputs,{"duration":5},rates) is None
    usage=measured(inputs,{"duration":5,"usage":{"input_video_duration":2}},rates)
    assert video_cost(usage,rates)==Decimal(6) and usage["duration_source"]=="provider"


async def test_reference_video_without_verified_usage_keeps_movie_but_does_not_debit(video_api,monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    app,key,model,team,local=video_api
    upstream=SimpleNamespace(submit=AsyncMock(return_value="up-2"),
        query=AsyncMock(return_value={"status":TaskStatusEnum.completed,"progress":100,
            "url":"https://cdn.example/movie.mp4","metadata":{"duration":5}}))
    monkeypatch.setattr("services.platform.videos.get_generator",lambda c:upstream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        headers={"Authorization":"Bearer "+key,"Idempotency-Key":"kept"}
        body={"model":local.model,"prompt":"test","duration":5,"aspect_ratio":"16:9","resolution":"720p",
              "references":[{"type":"video","url":"https://example.com/ref.mp4"}]}
        first=await c.post("/v1/videos",headers=headers,json=body)
        again=await c.post("/v1/videos",headers=headers,json=body)
        assert first.status_code==again.status_code==200 and first.json()["id"]==again.json()["id"]
        assert (await c.post("/v1/videos",headers=headers,json={**body,"prompt":"different"})).status_code==409
        got=(await c.get("/v1/videos/"+first.json()["id"],headers=headers)).json()
        assert got["status"]=="completed" and got["metadata"]["url"].endswith("movie.mp4") and got["billing_status"]=="review"
        upstream.submit.assert_awaited_once()
        assert not await BalanceTransaction.all().exists()


async def test_self_hosted_official_platform_config_tracks_cost_without_charging_local_wallet(video_api):
    from services.billing.recorder import billing_recorder
    from controllers.video import video_controller
    _,_,_,team,local=video_api
    await AiModelConfig.filter(id=local.id).update(scope="official",team_id=None,
        pricing={"type":"video","billing_unit":"second","prices":{"720p":1}})
    rec=await billing_recorder.record_video(novel_id=1, seconds=5,resolution="720p", model_config_id=local.id,team_id=team.id)
    await video_controller._consume_balance(rec,team.id)
    assert rec.cost_source=="team_key" and rec.cost==5
    assert not await BalanceTransaction.all().exists()
