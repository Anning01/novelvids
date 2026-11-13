"""Account console, read-only legacy migration and external developer API."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth.deps import AuthContext, require_roles, require_super_admin
from controllers.billing import billing_scope
from services.billing.aggregation import summary
from auth.models import PlatformApiKey, PlatformCallReceipt, StudioKeyGrant
from services.platform.temporary_media import UploadSpec, issue_upload
from schemas.platform_chat import ChatRequest
from schemas.platform_billing import PlatformReceiptOut, PlatformAccountOut
from services.platform.receipts import call_receipt
from services.platform.videos import VideoRequest, submit_video, video_status
from services.platform.images import ImageRequest, generate as generate_platform_image
from services.platform.chat import complete
from services.platform.access import console_owner, create_key, developer_identity, key_view, revoke_key, studio_identity
from services.platform.catalog import model_catalog
from services.platform.http_contract import DeveloperRoute
from services.platform.documentation import agent_guide
from services.platform.request_data import validated_body, sdk_request_schema
from utils.response_format import ResponseSchema
from api.billing import router as billing
from api.novel import export_project, export_with_canvases, get_project_overview
from api.video_export import download_export


console_router = APIRouter()
developer_router = APIRouter(route_class=DeveloperRoute)
console_router.include_router(billing, prefix="/billing")
from api.config import router as model_config_router
console_router.include_router(model_config_router, prefix="/config", dependencies=[Depends(require_super_admin)], include_in_schema=False)
console_router.add_api_route("/novel/overview", get_project_overview, methods=["GET"], include_in_schema=False)
console_router.add_api_route("/novel/{novel_id}/transfer", export_project, methods=["GET"], include_in_schema=False)
console_router.add_api_route("/novel/{novel_id}/transfer", export_with_canvases, methods=["POST"], include_in_schema=False)
console_router.add_api_route("/video/exports/{export_id}/download", download_export, methods=["GET"], include_in_schema=False)


class NewKey(BaseModel):
    purpose: Literal["api", "studio"] = "api"
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")


@console_router.get("/platform/usage", include_in_schema=False)
async def platform_usage(
    ctx: AuthContext = Depends(require_roles("admin", "creator")),
    days: Annotated[int | None, Query(ge=1, le=90)] = None,
):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(data=await summary(team_id=ctx.team_id if ctx.team_id is not None else team_id,
                                             user_id=user_id, cost_source="balance", recent_days=days))


@console_router.get("/platform/catalog")
async def console_catalog():
    return ResponseSchema(data=await model_catalog())


@console_router.get("/platform/keys", include_in_schema=False)
async def list_keys(ctx: AuthContext = Depends(console_owner)):
    rows = await PlatformApiKey.filter(user_id=ctx.user.id, team_id=ctx.team_id, revoked_at__isnull=True).order_by("-id")
    granted = set(await StudioKeyGrant.filter(key_id__in=[row.id for row in rows]).values_list("key_id", flat=True))
    return ResponseSchema(data=[{**key_view(row), "purpose":"studio" if row.id in granted else "api"} for row in rows])


@console_router.post("/platform/keys", include_in_schema=False)
async def new_key(body: NewKey, response: Response, ctx: AuthContext = Depends(console_owner)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await create_key(ctx, body.name.strip(), studio=body.purpose == "studio"))


@console_router.delete("/platform/keys/{key_id}", include_in_schema=False)
async def delete_key(key_id: int, ctx: AuthContext = Depends(console_owner)):
    await revoke_key(ctx, key_id)
    return ResponseSchema()


@developer_router.get("/agent-guide.md", include_in_schema=False)
async def ai_integration_guide(request: Request):
    base_url = str(request.url).split("?", 1)[0].removesuffix("/agent-guide.md")
    return Response(agent_guide(base_url), media_type="text/markdown")


@developer_router.get("/llms.txt", include_in_schema=False)
async def ai_document_index(request: Request):
    base_url = str(request.url).split("?", 1)[0].removesuffix("/llms.txt")
    return Response(f"# 猫影模型 API\n\n- [AI Agent 接入说明]({base_url}/agent-guide.md)\n- [OpenAPI]({base_url}/openapi.json)\n", media_type="text/plain")


@developer_router.get("/models", summary="列出当前平台模型")
async def models(_: AuthContext = Depends(developer_identity)):
    return {"object":"list","data":[{"object":"model", "owned_by":"novelvids", **item} for item in await model_catalog()]}


@developer_router.get("/account", summary="查询 Key 所属平台账户余额", response_model=PlatformAccountOut)
async def platform_account(request: Request, response: Response, ctx: AuthContext = Depends(developer_identity)):
    from auth.models import Team
    response.headers["Cache-Control"] = "no-store"
    team = await Team.get(id=ctx.team_id)
    origin = str(request.url).split("/v1/", 1)[0]
    return PlatformAccountOut(balance=team.balance, recharge_url=f"{origin}/#/profile?recharge=1&team={team.id}")



@developer_router.post("/chat/completions", summary="对话生成与流式返回")
async def chat_completions(body: ChatRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await complete(ctx, body, idempotency_key)


@developer_router.get("/requests/{request_id}", summary="查询调用及结算状态", response_model=PlatformReceiptOut)
async def call_status(request_id: UUID, response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await call_receipt(request_id, ctx)


@developer_router.get("/requests", summary="按原请求标识恢复结算回执", response_model=PlatformReceiptOut)
async def call_status_by_key(request_key: Annotated[str, Query(min_length=1, max_length=200)], response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await call_receipt(request_key, ctx, by_key=True)




@developer_router.post("/studio/media-lease", include_in_schema=False)
async def studio_media_lease(body: UploadSpec, response: Response, ctx: AuthContext = Depends(studio_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await issue_upload(ctx.team_id, body)


@developer_router.post("/images/generations", summary="生成图像并返回结果链接")
async def images(body: ImageRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await generate_platform_image(ctx, body, idempotency_key)


@developer_router.post("/images/edits", summary="使用已上传的参考图", openapi_extra=sdk_request_schema(ImageRequest))
async def edit_images(request: Request, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    body = validated_body(ImageRequest, await request.json())
    if not body.image:
        raise HTTPException(400, "image must contain reference URLs uploaded to temporary storage")
    return await generate_platform_image(ctx, body, idempotency_key)


@developer_router.post("/media/uploads", summary="申请临时 OSS 直传地址")
async def temporary_upload(body: UploadSpec, response: Response, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    return await issue_upload(ctx.team_id, body)


@developer_router.post("/videos", summary="提交视频生成", openapi_extra=sdk_request_schema(VideoRequest))
async def create_video(request: Request, response: Response, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    body = validated_body(VideoRequest, await request.json())
    job = await submit_video(ctx, body, idempotency_key)
    response.headers["X-Request-Id"] = job["id"]
    response.headers["Cache-Control"] = "no-store"
    return job


@developer_router.get("/videos/{identifier}", summary="查询视频生成状态及结果链接")
async def read_video(identifier: str, response: Response, refresh: bool = False, ctx: AuthContext = Depends(developer_identity)):
    response.headers["Cache-Control"] = "no-store"
    try:
        by_key = identifier.startswith("req-")
        value = UUID(identifier[4:] if by_key else identifier)
    except ValueError:
        raise HTTPException(404, "视频请求不存在") from None
    return await video_status(ctx, key=value,refresh=refresh) if by_key else await video_status(ctx, public_id=value,refresh=refresh)


@developer_router.get("/videos/{identifier}/content", summary="下载已完成的视频")
async def video_content(identifier: str, variant: Literal["video", "thumbnail", "spritesheet"] = "video",
    ctx: AuthContext = Depends(developer_identity)):
    if variant != "video":
        raise HTTPException(400, "Selected provider does not expose this video variant")
    try:
        value = UUID(identifier)
    except ValueError:
        raise HTTPException(404, "Video not found") from None
    job = await video_status(ctx, public_id=value, refresh=True)
    url = (job.get("metadata") or {}).get("url")
    if job["status"] != "completed" or not url:
        raise HTTPException(409, "Video is not ready")
    return RedirectResponse(url, status_code=307, headers={"Cache-Control":"no-store"})
