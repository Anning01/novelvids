import json
from decimal import Decimal
import httpx
import pytest
from fastapi import FastAPI

from api.platform import developer_router
from auth.deps import AuthContext
from auth.models import PlatformCallReceipt, Team, TeamMember, User
from config import settings
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.platform.access import create_key

pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires platform authentication")


@pytest.fixture
async def image_api():
    app=FastAPI()
    app.include_router(developer_router,prefix="/v1")
    user=await User.create(username="image-api-user",password_hash="!")
    team=await Team.create(name="图片调用",balance=10)
    member=await TeamMember.create(user=user,team=team,role="creator")
    token=(await create_key(AuthContext(user=user,team_id=team.id,membership=member),"studio",studio=True))["key"]
    model=await AiModelConfig.create(name="示例生图",task_type=2,is_active=True,api_protocol="volcengine_ark",
        base_url="https://vendor.example/v3",api_key="test-vendor",model="vendor-model",image_model_type="seedream_5_pro",
        pricing={"type":"image","prices":{"2K":0.5},"input_image":{"first_free":0,"price_per_image":0.1},"discount":0.5})
    return app, token, model, team


async def test_local_image_entry_routes_original_through_oss_and_result_direct_from_supplier(image_api, monkeypatch, tmp_path):
    import base64
    from services.image_generation.gateway import generate_images
    from services.reference.handler import _persist_generated_image
    from pathlib import Path

    app,token,model,team=image_api
    original=httpx.AsyncClient
    router=httpx.ASGITransport(app=app)
    uploads={}
    seen=[]
    for k,v in {"MEDIA_PATH":str(tmp_path/"media"),"STUDIO_MEDIA_CACHE_PATH":str(tmp_path/"cache"),
        "STUDIO_TEMP_BUCKET":"example-bucket","STUDIO_TEMP_REGION":"cn-hangzhou","OSS_ACCESS_KEY_ID":"fixture",
        "OSS_ACCESS_KEY_SECRET":"fixture-secret","DEPLOYMENT_ROLE":"studio"}.items():
        monkeypatch.setattr(settings,k,v)
    raw=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y9F8AAAAASUVORK5CYII=")
    async def dispatch(req):
        seen.append((req.url.host,req.url.path))
        if req.url.host=="platform.example":
            if req.url.path.endswith("generations"):
                submitted=json.loads(req.content)
                assert submitted["model"]==f"nv-{model.id}" and "base64" not in req.content.decode()
            return await router.handle_async_request(req)
        if req.url.host.endswith(".aliyuncs.com"):
            assert "authorization" not in req.headers
            uploads[req.url.path]=await req.aread()
            return httpx.Response(200)
        if req.url.host=="vendor.example":
            body=json.loads(req.content)
            assert body["model"]=="vendor-model" and body["response_format"]=="url" and body["size"]=="2816x1584"
            assert httpx.URL(body["image"][0]).path in uploads
            return httpx.Response(200,json={"data":[{"url":"https://images.example/result.png"}]})
        assert req.url.host=="images.example" and "authorization" not in req.headers
        return httpx.Response(200,content=raw,headers={"Content-Type":"image/png"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:original(**kw,transport=httpx.MockTransport(dispatch)))
    images=await generate_images(base_url="https://platform.example/v1",api_key=token,model=f"nv-{model.id}",
        api_protocol="novelvids",prompt="场景",resolution="2816x1584",aspect_ratio="16:9",
        extra_body={"image":["data:image/png;base64,"+base64.b64encode(raw).decode()]})
    assert seen[-1]==("vendor.example","/v3/images/generations")
    from types import SimpleNamespace
    monkeypatch.setattr("services.oss.oss", SimpleNamespace(enabled=True))
    saved=await _persist_generated_image(images[0],10,"_test")
    assert seen[-1]==("images.example","/result.png") and (Path(settings.MEDIA_PATH)/saved.removeprefix("/media/")).read_bytes()==raw
    record=await ModelUsageRecord.get()
    await team.refresh_from_db()
    assert record.billing_type=="image" and record.cost==Decimal(".30")
    assert team.balance==Decimal("9.70") and record.usage["image_count"]==record.usage["input_image_count"]==1


async def test_unsupported_media_is_rejected_before_upstream_or_debit(image_api):
    app,token,model,_=image_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        headers={"Authorization":"Bearer "+token}
        body={"model":f"nv-{model.id}","prompt":"测试","image":["data:image/png;base64,abc"]}
        assert (await client.post("/v1/images/generations",headers=headers,json=body)).status_code==422
        await AiModelConfig.filter(id=model.id).update(image_model_type="gpt_image_2",api_protocol="openai_compatible")
        body["image"]=["https://cdn.example/input.png"]
        assert (await client.post("/v1/images/generations",headers=headers,json=body)).status_code==422
        assert not await PlatformCallReceipt.all().exists() and not await ModelUsageRecord.all().exists()
