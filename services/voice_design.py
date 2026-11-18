"""Design a sample for one saved character or form and bind it safely."""

from dataclasses import dataclass
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auth.deps import AuthContext, ensure_novel_access
from config import settings
from controllers._creation import creation_write
from controllers.config import ai_model_config_controller, general_config_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.novel import Novel
from prompts.voice_design import render_voice_design
from schemas.creation_agent import AgentConfiguration
from schemas.media_library import AudioReferenceAutoDesignIn
from schemas.voice_design import VoiceAudioOptions, VoiceDesignRequest, VoiceMessage
from services.audio_references import _create_reference, _validate_audio_file
from services.billing.pricing import validate_voice_design_pricing
from services.billing.voice_design import run_voice_model
from services.catalog_applications import bound_voice_metadata, metadata_dict
from services.creation_agent.handler import configured_model
from services.oss import make_upload_key, oss
from services.voice_design_protocol import VOICE_PROTOCOLS, synthesize_voice
from utils.enums import AiTaskTypeEnum, AssetTypeEnum
from utils.messages import localized_message as msg

logger = logging.getLogger(__name__)


class VoiceDesignDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    voice_description: str = Field(min_length=1, max_length=400)
    sample_text: str = Field(min_length=1, max_length=400)
    gender: Literal["male", "female", "unspecified"]


@dataclass(frozen=True)
class VoiceTarget:
    asset: Asset
    variant: AssetVariant | None

    @property
    def row(self) -> Asset | AssetVariant:
        return self.variant or self.asset

    @property
    def binding(self) -> tuple[int | None, str]:
        metadata = metadata_dict(self.row.metadata)
        editor_form = metadata_dict(metadata.get("editor_form"))
        raw_id = metadata.get("voice_reference_id", editor_form.get("voice_reference_id"))
        try:
            reference_id = int(raw_id) if raw_id is not None else 0
        except (TypeError, ValueError):
            reference_id = 0
        nickname = metadata.get("voice", editor_form.get("voice"))
        return reference_id if reference_id > 0 else None, nickname.strip() if isinstance(nickname, str) else ""

    def facts(self, project: Novel) -> dict[str, str]:
        def details(row, key):
            metadata = metadata_dict(row.metadata)
            editor_form = metadata_dict(metadata.get("editor_form"))
            return editor_form.get(key) or metadata.get(key)

        def field(*values):
            return next((str(value)[:1200] for value in values if value), "")

        asset, row = self.asset, self.row
        return {
            "project": project.name,
            "name": asset.canonical_name,
            "form": self.variant.name if self.variant else "",
            "gender": field(details(row, "gender"), details(asset, "gender")),
            "age": field(details(row, "age_group"), details(row, "age"), details(asset, "age_group"), details(asset, "age")),
            "description": field(row.description, asset.description),
            "traits": field(row.base_traits, asset.base_traits),
        }

    def binding_metadata(self, reference):
        metadata = metadata_dict(self.row.metadata)
        if self.variant:
            metadata = {**metadata, "editor_form": metadata_dict(metadata.get("editor_form"))}
        return bound_voice_metadata(metadata, reference)


async def _target(payload: AudioReferenceAutoDesignIn, ctx: AuthContext) -> tuple[Novel, VoiceTarget]:
    asset = await Asset.get_or_none(id=payload.asset_id)
    if asset is None:
        raise HTTPException(404, msg("角色资产不存在"))
    await ensure_novel_access(asset.novel_id, ctx)
    project = await Novel.get_or_none(id=asset.novel_id)
    if project is None:
        raise HTTPException(404, msg("项目不存在"))
    if asset.asset_type != AssetTypeEnum.person.value or metadata_dict(asset.metadata).get("reference_layout") == "group_portrait":
        raise HTTPException(422, msg("仅单独的人物角色支持自动设计音色"))
    variant = None
    if payload.variant_id is not None:
        variant = await AssetVariant.get_or_none(id=payload.variant_id, asset_id=asset.id)
        if variant is None:
            raise HTTPException(404, msg("资产形态不存在"))
    target = VoiceTarget(asset, variant)
    if target.binding != (payload.expected_voice_reference_id, payload.expected_voice.strip()):
        raise HTTPException(409, msg("绑定的音色已变化，请刷新后重新确认"))
    return project, target


async def _describe_voice(config, *, project, user_id, facts, language) -> VoiceDesignDraft:
    from pydantic_ai import Agent
    from pydantic_ai.exceptions import AgentRunError, ModelHTTPError

    system, prompt = render_voice_design(facts, language)

    async def execute(client):
        model = configured_model(config, AgentConfiguration(), http_client=client)
        result = await Agent(model, instructions=system, retries=0).run(prompt)
        usage = result.usage()
        return result.output, {
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
        }

    try:
        raw = await run_voice_model(config, project=project, user_id=user_id, kind="text", execute=execute)
        return VoiceDesignDraft.model_validate_json(raw)
    except ModelHTTPError as error:
        if error.status_code == 402:
            raise HTTPException(402, msg("模型账户可用额度不足")) from None
        raise HTTPException(502, msg("角色音色描述生成失败，请检查文本模型后重试")) from None
    except (ValidationError, AgentRunError):
        raise HTTPException(502, msg("角色音色描述生成失败，请检查文本模型后重试")) from None


async def auto_design_voice_for_asset(payload: AudioReferenceAutoDesignIn, ctx: AuthContext):
    project, target = await _target(payload, ctx)
    voice_config = await ai_model_config_controller.get_active(AiTaskTypeEnum.voice_design.value, team_id=project.team_id)
    try:
        if voice_config.api_protocol not in VOICE_PROTOCOLS or not voice_config.api_key or not voice_config.base_url:
            raise ValueError
        validate_voice_design_pricing(voice_config.pricing)
    except ValueError:
        raise HTTPException(409, msg("请先配置音色设计模型、密钥和价格")) from None
    text_config = await ai_model_config_controller.get_active_with_legacy_fallback(
        AiTaskTypeEnum.project_analysis.value, AiTaskTypeEnum.extraction.value, team_id=project.team_id,
    )
    language = await general_config_controller.get_prompt_language()
    user_id = ctx.user.id if ctx.user else None
    facts = target.facts(project)
    draft = await _describe_voice(text_config, project=project, user_id=user_id, facts=facts, language=language)
    request = VoiceDesignRequest(model=voice_config.model, audio=VoiceAudioOptions(), messages=[
        VoiceMessage(role="user", content=draft.voice_description),
        VoiceMessage(role="assistant", content=draft.sample_text),
    ])

    async def execute(client):
        sample = await synthesize_voice(client, voice_config, request)
        return sample, {"seconds": sample.seconds}

    sample = await run_voice_model(voice_config, project=project, user_id=user_id,
                                   kind="voice_design", execute=execute)
    with TemporaryDirectory(prefix="voice-design-") as directory:
        path = Path(directory) / "sample.wav"
        path.write_bytes(sample.data)
        duration = await _validate_audio_file(path)
        return await _bind_sample(payload, ctx, project, path, duration, draft)


async def _bind_sample(payload, ctx, project, path, duration, draft):
    remote = oss.enabled
    destination = Path(settings.MEDIA_PATH) / "audio-references" / f"{uuid4().hex}.wav"
    key = make_upload_key(project.team_id, "voice-design.wav") if remote else f"/media/audio-references/{destination.name}"
    try:
        if remote:
            await oss.put_file(key, path, "audio/wav")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        async with creation_write(project.id):
            current_project, target = await _target(payload, ctx)
            if current_project.id != project.id or current_project.team_id != project.team_id:
                raise HTTPException(409, msg("项目归属已变化，请刷新后重试"))
            name = target.asset.canonical_name
            if target.variant:
                name += f"·{target.variant.name}"
            gender = {"male": "男", "female": "女", "unspecified": "未设置"}[draft.gender]
            reference = await _create_reference(
                nickname=f"{name}-{current_project.name}"[:100], gender=gender, audio_url=key, duration=duration,
                team_id=current_project.team_id, created_by=current_project.created_by if current_project.team_id is None
                else ctx.user.id if ctx.user else None,
            )
            target.row.metadata = target.binding_metadata(reference)
            await target.row.save(update_fields=["metadata", "updated_at"])
        return reference, target.row.metadata
    except BaseException:
        try:
            if remote:
                await oss.delete(key)
            else:
                destination.unlink(missing_ok=True)
        except Exception as error:
            logger.warning("Voice sample cleanup failed type=%s", type(error).__name__)
        raise
