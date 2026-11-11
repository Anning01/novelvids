"""Account console, read-only legacy migration and external developer API."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from auth.deps import AuthContext, require_roles
from controllers.billing import billing_scope
from services.billing.aggregation import summary
from auth.models import PlatformApiKey, PlatformCallReceipt
from schemas.platform_chat import ChatRequest
from services.platform.chat import complete
from services.platform.access import console_owner, create_key, developer_identity, key_view, revoke_key
from services.platform.catalog import model_catalog
from utils.response_format import ResponseSchema
from api.billing import router as billing
from api.novel import export_project, get_project_overview
from api.video_export import download_export


console_router = APIRouter()
developer_router = APIRouter()
console_router.include_router(billing, prefix="/billing")
console_router.add_api_route("/novel/overview", get_project_overview, methods=["GET"], include_in_schema=False)
console_router.add_api_route("/novel/{novel_id}/transfer", export_project, methods=["GET"], include_in_schema=False)
console_router.add_api_route("/video/exports/{export_id}/download", download_export, methods=["GET"], include_in_schema=False)


class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")


@console_router.get("/platform/usage", include_in_schema=False)
async def platform_usage(ctx: AuthContext = Depends(require_roles("admin", "creator"))):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(data=await summary(team_id=ctx.team_id if ctx.team_id is not None else team_id,
                                             user_id=user_id, cost_source="balance"))


@console_router.get("/platform/catalog")
async def console_catalog():
    return ResponseSchema(data=await model_catalog())


@console_router.get("/platform/keys", include_in_schema=False)
async def list_keys(ctx: AuthContext = Depends(console_owner)):
    rows = await PlatformApiKey.filter(user_id=ctx.user.id, team_id=ctx.team_id, revoked_at__isnull=True).order_by("-id")
    return ResponseSchema(data=[key_view(row) for row in rows])


@console_router.post("/platform/keys", include_in_schema=False)
async def new_key(body: NewKey, response: Response, ctx: AuthContext = Depends(console_owner)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await create_key(ctx, body.name.strip()))


@console_router.delete("/platform/keys/{key_id}", include_in_schema=False)
async def delete_key(key_id: int, ctx: AuthContext = Depends(console_owner)):
    await revoke_key(ctx, key_id)
    return ResponseSchema()


@developer_router.get("/models", summary="列出当前平台模型")
async def models(_: AuthContext = Depends(developer_identity)):
    return {"object":"list","data":[{"object":"model", "owned_by":"novelvids", **item} for item in await model_catalog()]}



@developer_router.post("/chat/completions", summary="对话生成与流式返回")
async def chat_completions(body: ChatRequest, ctx: AuthContext = Depends(developer_identity),
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
    return await complete(ctx, body, idempotency_key)


@developer_router.get("/requests/{request_id}", summary="查询调用及结算状态")
async def call_status(request_id: UUID, ctx: AuthContext = Depends(developer_identity)):
    row = await PlatformCallReceipt.get_or_none(public_id=request_id, team_id=ctx.team_id, user_id=ctx.user.id)
    if not row:
        raise HTTPException(404, "请求不存在")
    return {"id": str(row.public_id), "model": f"nv-{row.model_config_id}", "status": row.state, "usage": row.usage}
