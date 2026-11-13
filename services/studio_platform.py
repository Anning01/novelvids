"""Synchronize public model capabilities and prices without importing upstream secrets."""
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from config import settings
from models.config import AiModelConfig, StudioPlatformConnection
from services.platform.catalog import PUBLIC_KINDS, public_tariff
from utils.enums import ImageModelTypeEnum, VideoGenerationModelTypeEnum
from utils.messages import localized_message
from schemas.platform_billing import PlatformAccountOut


SYNC_SCOPE = "studio_platform"


class CatalogModel(BaseModel):
    id: str = Field(pattern=r"^nv-[1-9][0-9]{0,9}$")
    name: str = Field(min_length=1, max_length=100)
    task_types: list[int] = Field(min_length=1)
    image_model_type: ImageModelTypeEnum | None = None
    video_model_type: VideoGenerationModelTypeEnum | None = None
    tool_calls: bool = False
    json_output: bool = False
    pricing: dict | None = None


class Catalog(BaseModel):
    data: list[CatalogModel]


def platform_base_url() -> str:
    url = settings.STUDIO_PLATFORM_BASE_URL
    parts = urlsplit(url)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or not (
        parts.scheme == "https" or parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(409, localized_message("请先设置工作台的平台地址"))
    return url if url.endswith("/v1") else url + "/v1"


async def platform_connection_status() -> dict:
    row = await StudioPlatformConnection.get_or_none(id=1)
    return {"connected": bool((row and row.api_key) or settings.STUDIO_PLATFORM_API_KEY)}


async def platform_account() -> PlatformAccountOut:
    base_url = platform_base_url()
    row = await StudioPlatformConnection.get_or_none(id=1)
    key = row.api_key if row and row.api_key else settings.STUDIO_PLATFORM_API_KEY
    if not key:
        raise HTTPException(409, localized_message("请先填写平台 API Key"))
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.get(base_url + "/account", headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        account = PlatformAccountOut.model_validate(response.json())
        target, source = urlsplit(account.recharge_url), urlsplit(base_url)
        if (target.scheme, target.netloc) != (source.scheme, source.netloc):
            raise ValueError("Invalid platform recharge destination")
        return account
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, localized_message("暂时无法读取平台账户，请在平台查看")) from None


async def sync_platform_models(replacement: str | None = None) -> dict:
    base_url = platform_base_url()
    connection, _ = await StudioPlatformConnection.get_or_create(id=1, defaults={"api_key": ""})
    key = replacement or connection.api_key or settings.STUDIO_PLATFORM_API_KEY
    if not key:
        raise HTTPException(409, localized_message("请先填写平台 API Key"))
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.get(base_url + "/models", headers={"Authorization": f"Bearer {key}"})
        if response.status_code in (401, 403):
            raise HTTPException(422, localized_message("平台 API Key 无效或无权访问"))
        response.raise_for_status()
        catalog = Catalog.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError):
        raise HTTPException(502, localized_message("暂时无法读取平台模型目录")) from None

    async with in_transaction() as db:
        query = StudioPlatformConnection.filter(id=1).using_db(db)
        await query.update(api_key=F("api_key"))
        if (await query.get()).api_key != connection.api_key:
            raise HTTPException(409, localized_message("平台 API Key 已变更，请重新同步"))
        synced = AiModelConfig.filter(scope=SYNC_SCOPE, team_id=None).using_db(db)
        seen = set()
        for entry in catalog.data:
            capabilities = sorted(set(entry.task_types).intersection(PUBLIC_KINDS))
            if not capabilities or entry.id in seen:
                continue
            seen.add(entry.id)
            values = dict(name=f"{entry.name[:83]} · {entry.id}", task_type=capabilities[0], task_types=capabilities,
                          base_url=base_url, api_key=key, api_protocol="novelvids", is_active=True,
                          image_model_type=entry.image_model_type, video_model_type=entry.video_model_type,
                          supports_tool_calls=entry.tool_calls, supports_json_output=entry.json_output)
            row = await synced.filter(model=entry.id).first()
            if row:
                row.update_from_dict(values)
                await row.save(using_db=db, update_fields=[*values, "updated_at"])
            else:
                await AiModelConfig.create(using_db=db, model=entry.id, scope=SYNC_SCOPE,
                    pricing=public_tariff(entry.pricing) or None, **values)
        await synced.exclude(model__in=seen).update(is_active=False)
        if replacement:
            await query.update(api_key=key)
    return {"connected": True, "synced": len(seen)}
