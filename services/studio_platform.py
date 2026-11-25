"""Synchronize public model capabilities and prices without importing upstream secrets."""
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from config import settings
from models.config import AiModelConfig, StudioPlatformConnection
from services.platform.catalog import PUBLIC_KINDS, public_tariff
from utils.enums import AiTaskTypeEnum, ImageModelTypeEnum, VideoGenerationModelTypeEnum
from services.video.capabilities import platform_video_capabilities
from services.video_enhancement.contract import EnhancementOptions
from utils.messages import localized_message
from schemas.platform_billing import PlatformAccountOut


SYNC_SCOPE = "studio_platform"
SYNC_TASK_TYPES = {*PUBLIC_KINDS, AiTaskTypeEnum.video_enhancement.value, AiTaskTypeEnum.audio_recognition.value}
PUBLIC_PROCESSING_FIELDS = set(EnhancementOptions.model_fields) - {"queue_id", "media_base_url", "account_concurrency"}


class CatalogModel(BaseModel):
    id: str = Field(pattern=r"^nv-[1-9][0-9]{0,9}$")
    name: str = Field(min_length=1, max_length=100)
    task_types: list[int] = Field(min_length=1)
    image_model_type: str | None = None
    video_model_type: str | None = None
    video_capabilities: object | None = None
    concurrency: int = Field(default=1, ge=1)
    is_active: bool = True
    tool_calls: bool = False
    json_output: bool = False
    text_api: Literal["chat_completions", "responses"] = "chat_completions"
    strict_output: bool = False
    schema_in_prompt: bool = False
    pricing: dict | None = None
    processing_options: dict | None = None


def video_tariff_error(entry: CatalogModel) -> str | None:
    raw = entry.pricing or {}
    if entry.video_model_type and raw.get("type") == "video":
        unit = raw.get("billing_unit", "token")
        if unit not in ("token", "second", "call", "per_video"):
            return f"billing_unit={unit}"
        if raw.get("currency", "CNY") != "CNY":
            return f"currency={raw.get('currency')}"
    return None


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
    return {"connected": bool((row and row.api_key) or settings.STUDIO_PLATFORM_API_KEY),
            "key_management_url": platform_base_url().removesuffix("/v1") + "/#/platform/keys"}


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


async def _read_platform_catalog(replacement: str | None = None):
    base_url = platform_base_url()
    connection, _ = await StudioPlatformConnection.get_or_create(id=1, defaults={"api_key": ""})
    key = replacement or connection.api_key or settings.STUDIO_PLATFORM_API_KEY
    if not key:
        raise HTTPException(409, localized_message("请先填写平台 API Key"))
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.get(base_url + "/models", headers={"Authorization": f"Bearer {key}",
                "X-NovelVids-Capabilities": "pixel_tier_images"})
        if response.status_code in (401, 403):
            raise HTTPException(422, localized_message("平台 API Key 无效或无权访问"))
        response.raise_for_status()
        catalog = Catalog.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError):
        raise HTTPException(502, localized_message("暂时无法读取平台模型目录")) from None

    return connection, base_url, key, catalog


async def platform_image_tariff(config_id: int) -> dict:
    row = await AiModelConfig.get_or_none(id=config_id, scope=SYNC_SCOPE, team_id=None)
    if row is None or not row.image_model_type:
        raise HTTPException(404, "未找到平台生图配置")
    _, _, _, catalog = await _read_platform_catalog()
    for entry in catalog.data:
        if entry.id == row.model and entry.is_active and entry.image_model_type == row.image_model_type:
            tariff = public_tariff(entry.pricing)
            if tariff.get("type") == "image" and tariff.get("prices"):
                return tariff
    raise HTTPException(409, "平台尚未提供该渠道的图片价格")


async def validate_model_activation(row: AiModelConfig) -> None:
    """A local switch cannot restore a withdrawn or incompatible remote model."""
    _, _, _, catalog = await _read_platform_catalog()
    entry = next((entry for entry in catalog.data if entry.id == row.model), None)
    if entry and entry.video_capabilities is not None:
        try:
            current = platform_video_capabilities(entry.video_capabilities).public_dict()
        except ValueError:
            raise HTTPException(409, "平台视频能力无效，请重新同步目录") from None
        if (row.processing_options or {}).get("video_capabilities") != current:
            raise HTTPException(409, "平台视频能力已变更，请重新同步目录")
    elif entry and (row.processing_options or {}).get("video_capabilities"):
        raise HTTPException(409, "平台视频能力已变更，请重新同步目录")
    if (entry is None or not entry.is_active or video_tariff_error(entry) or
            entry.image_model_type != row.image_model_type or entry.video_model_type != row.video_model_type or
            not set(entry.task_types).intersection(SYNC_TASK_TYPES)):
        raise HTTPException(409, localized_message("该平台模型当前不可用，请同步模型目录后再试"))


async def sync_platform_models(replacement: str | None = None) -> dict:
    connection, base_url, key, catalog = await _read_platform_catalog(replacement)
    async with in_transaction() as db:
        query = StudioPlatformConnection.filter(id=1).using_db(db)
        await query.update(api_key=F("api_key"))
        if (await query.get()).api_key != connection.api_key:
            raise HTTPException(409, localized_message("平台 API Key 已变更，请重新同步"))
        synced = AiModelConfig.filter(scope=SYNC_SCOPE, team_id=None).using_db(db)
        seen = set()
        unsupported = {}
        for entry in catalog.data:
            capabilities = sorted(set(entry.task_types).intersection(SYNC_TASK_TYPES))
            if not entry.is_active or not capabilities or entry.id in seen:
                continue
            unknown = []
            processing_options = {}
            if entry.image_model_type is not None and entry.image_model_type not in ImageModelTypeEnum:
                unknown.append(entry.image_model_type)
            if entry.video_capabilities is not None:
                try:
                    if not entry.video_model_type or len(entry.video_model_type) > 40 or AiTaskTypeEnum.video not in capabilities:
                        raise ValueError
                    processing_options["video_capabilities"] = platform_video_capabilities(entry.video_capabilities).public_dict()
                except ValueError:
                    unknown.append("video_capabilities")
            elif entry.video_model_type is not None and entry.video_model_type not in VideoGenerationModelTypeEnum:
                unknown.append(entry.video_model_type)
            tariff_error = video_tariff_error(entry)
            if tariff_error:
                unknown.append(tariff_error)
            if unknown:
                unsupported[entry.id] = ", ".join(unknown)
                await synced.filter(model=entry.id).update(is_active=False, api_key=key)
                continue
            seen.add(entry.id)
            if AiTaskTypeEnum.voice_design in capabilities:
                from services.billing.pricing import validate_voice_design_pricing

                try:
                    if capabilities != [AiTaskTypeEnum.voice_design]:
                        raise ValueError
                    validate_voice_design_pricing(public_tariff(entry.pricing))
                except ValueError:
                    unsupported[entry.id] = "voice_design"
                    await synced.filter(model=entry.id).update(is_active=False, api_key=key)
                    continue
            if AiTaskTypeEnum.video_enhancement.value in capabilities and entry.processing_options is not None:
                try:
                    options = EnhancementOptions.model_validate({
                        field: value for field, value in entry.processing_options.items() if field in PUBLIC_PROCESSING_FIELDS
                    })
                    processing_options.update(options.model_dump(mode="json", include=PUBLIC_PROCESSING_FIELDS))
                except ValidationError:
                    raise HTTPException(502, localized_message("平台画质增强能力配置无效")) from None
            row = await synced.filter(model=entry.id).select_for_update().first()
            name = entry.name
            conflicts = AiModelConfig.filter(task_type=capabilities[0]).using_db(db)
            if row:
                conflicts = conflicts.exclude(id=row.id)
            serial = 1
            while await conflicts.filter(name=name).exists():
                suffix = f" ({entry.id})" if serial == 1 else f" ({entry.id}-{serial})"
                name = entry.name[:100 - len(suffix)] + suffix
                serial += 1
            values = dict(name=name, task_type=capabilities[0], task_types=capabilities,
                          base_url=base_url, api_key=key, api_protocol="novelvids", is_active=row.local_enabled if row else True, concurrency=entry.concurrency,
                          image_model_type=entry.image_model_type, video_model_type=entry.video_model_type,
                          supports_tool_calls=entry.tool_calls, supports_json_output=entry.json_output,
                          supports_strict_output=entry.strict_output, schema_in_prompt=entry.schema_in_prompt, text_api=entry.text_api,
                          processing_options=processing_options or None)
            raw = entry.pricing or {}
            tariff = public_tariff(raw)
            if entry.video_model_type and raw.get("type") == "video":
                unit = raw.get("billing_unit", "token")
                tariff["billing_unit"] = "per_video" if unit == "call" else unit
            if row:
                if entry.video_model_type and tariff.get('type') == 'video' and tariff.get('prices'):
                    # Refresh base rates and tiers together; keep locally configured markups.
                    local = row.pricing or {}
                    values['pricing'] = {**tariff, **{key: local[key] for key in ('discount', 'discount_description') if key in local}}
                row.update_from_dict(values)
                await row.save(using_db=db, update_fields=[*values, "updated_at"])
            else:
                await AiModelConfig.create(using_db=db, model=entry.id, scope=SYNC_SCOPE,
                    pricing=tariff or None, **values)
        if unsupported and not seen:
            # Keep local prices and outstanding receipt associations; stale channels must not be offered.
            await synced.exclude(model__in=unsupported).update(is_active=False)
        else:
            await synced.exclude(model__in=seen.union(unsupported)).delete()
        from services.model_config_seed import remove_unused_seed_configs
        await remove_unused_seed_configs(db)
        if replacement:
            await query.update(api_key=key)
    return {"connected": True, "synced": len(seen), **({"unsupported": unsupported} if unsupported else {})}
