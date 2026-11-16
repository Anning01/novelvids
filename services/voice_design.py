"""全自动音色链：LLM 生成音色描述 → MiMo TTS 设计音色 → 上传对象存储 → 绑定角色。

链路（对应「逐角色按钮触发」的前端入口）：
1. 读取角色资产（名称/性别/年龄/人设描述/底色），调用项目分析同款 LLM
   生成一段中文音色描述与一句示例台词；
2. 调用小米 MiMo `mimo-v2.5-tts-voicedesign`（OpenAI 对话格式，
   api-key 鉴权）按描述合成 WAV 试听样本；
3. 样本校验（1-30 秒，与参考音频入库规则一致）后上传对象存储，
   创建 AudioReference（source=upload，可复用可裁剪）；
4. 把 voice_reference_id 写回角色（或衍生形态）metadata，完成绑定。
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import httpx
from fastapi import HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from config import settings
from controllers.config import ai_model_config_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.novel import Novel
from services.audio_references import _create_reference, _validate_audio_file
from services.llm.json_output import create_json_completion
from services.oss import make_upload_key, oss
from utils.enums import AiTaskTypeEnum, AssetTypeEnum
from utils.messages import localized_message

MIMO_CHAT_COMPLETIONS_URL = "https://api.xiaomimimo.com/v1/chat/completions"
MIMO_VOICE_DESIGN_MODEL = "mimo-v2.5-tts-voicedesign"


class VoiceDesignDraft(BaseModel):
    """LLM 产出的音色设计稿。"""

    voice_description: str = Field(description="一段中文音色描述，覆盖性别、年龄感、音质、情绪基调、语速节奏，60 字以内")
    sample_text: str = Field(description="一句符合该角色身份的示例台词，15-30 字，用于试听")
    gender: str = Field(description="该音色对应的性别，只能是「男」或「女」")


def _normalize_gender(*candidates: str) -> str:
    """把角色资料/LLM 输出的性别归一化为「男/女」；无法判断时回退「未设置」。"""
    for value in candidates:
        text = str(value or "")
        if not text:
            continue
        if "女" in text:
            return "女"
        if "男" in text:
            return "男"
    return "未设置"


def _metadata_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _character_facts(asset: Asset, variant: AssetVariant | None) -> dict[str, str]:
    """汇总角色事实，供 LLM 设计音色。"""
    metadata = _metadata_dict(variant.metadata if variant else asset.metadata)
    editor_form = _metadata_dict(metadata.get("editor_form"))
    gender = (
        editor_form.get("gender")
        or metadata.get("gender")
        or ""
    )
    age_group = (
        editor_form.get("age_group")
        or metadata.get("age_group")
        or metadata.get("age")
        or ""
    )
    description = (
        (variant.description if variant else None)
        or asset.description
        or ""
    )
    traits = (
        (variant.base_traits if variant else None)
        or asset.base_traits
        or ""
    )
    return {
        "name": asset.canonical_name,
        "variant": variant.name if variant else "",
        "gender": str(gender),
        "age_group": str(age_group),
        "description": str(description),
        "traits": str(traits),
    }


def _render_design_messages(facts: dict[str, str], novel_name: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是配音导演。根据角色信息设计 TTS 音色描述、一句试听台词，并给出音色性别（男/女）。"
                "音色描述要具体到可执行的声学特征（性别、年龄感、音高、音质、"
                "情绪基调、语速），不要泛泛而谈。台词必须贴合角色身份与剧情语境。"
                "角色资料未注明性别时，根据人设与台词合理判断。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"剧目：{novel_name}\n"
                f"角色：{facts['name']}"
                + (f"（形态：{facts['variant']}）" if facts["variant"] else "")
                + f"\n性别：{facts['gender'] or '未知'}"
                f"\n年龄段：{facts['age_group'] or '未知'}"
                f"\n人设：{facts['description'] or '无'}"
                f"\n外形/性格底色：{facts['traits'][:400] or '无'}"
                "\n\n请输出该角色的音色设计稿。"
            ),
        },
    ]


async def _llm_voice_draft(
    facts: dict[str, str],
    novel_name: str,
    *,
    team_id: int | None,
) -> VoiceDesignDraft:
    """用项目分析同款模型生成音色描述（与项目分析同一配置入口）。"""
    llm_config = await ai_model_config_controller.get_active_with_legacy_fallback(
        AiTaskTypeEnum.project_analysis.value,
        AiTaskTypeEnum.extraction.value,
        team_id=team_id,
    )
    client = AsyncOpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)
    draft, _ = await create_json_completion(
        client,
        model=llm_config.model,
        messages=_render_design_messages(facts, novel_name),
        response_model=VoiceDesignDraft,
        prompt_language="zh",
        supports_json_output=getattr(llm_config, "supports_json_output", False),
    )
    return draft


async def _mimo_design_voice(draft: VoiceDesignDraft) -> bytes:
    """调用 MiMo TTS VoiceDesign，返回 WAV 字节。"""
    if not settings.MIMO_API_KEY:
        raise HTTPException(500, detail=localized_message("未配置 MiMo API Key（MIMO_API_KEY）"))
    payload = {
        "model": MIMO_VOICE_DESIGN_MODEL,
        "messages": [
            {"role": "user", "content": draft.voice_description},
            {"role": "assistant", "content": draft.sample_text},
        ],
        "audio": {"format": "wav"},
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            MIMO_CHAT_COMPLETIONS_URL,
            headers={
                "api-key": settings.MIMO_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code != 200:
        raise HTTPException(
            502,
            detail=localized_message(
                "MiMo 音色设计接口返回 {p1}：{p2}",
                p1=str(response.status_code),
                p2=response.text[:200],
            ),
        )
    try:
        audio = response.json()["choices"][0]["message"]["audio"]
        return base64.b64decode(audio["data"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(502, detail=localized_message("MiMo 返回的音频数据无法解析")) from exc


async def auto_design_voice_for_asset(
    *,
    asset_id: int,
    variant_id: int | None,
    novel_id: int | None,
    team_id: int | None,
    created_by: int | None,
) -> tuple[AudioReference, Asset, AssetVariant | None, VoiceDesignDraft]:
    """全自动音色链主入口：生成→合成→入库→绑定。"""
    if not oss.enabled:
        raise HTTPException(400, detail=localized_message("自动音色需要先启用对象存储（OSS）"))
    asset = await Asset.get_or_none(id=asset_id)
    if asset is None:
        raise HTTPException(404, detail=localized_message("角色资产不存在"))
    if asset.asset_type != AssetTypeEnum.person.value:
        raise HTTPException(400, detail=localized_message("仅人物角色支持自动设计音色"))
    variant: AssetVariant | None = None
    if variant_id:
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant is None:
            raise HTTPException(404, detail=localized_message("衍生形态不存在"))
    novel = await Novel.get_or_none(id=novel_id or asset.novel_id)
    novel_name = novel.name if novel else ""

    facts = _character_facts(asset, variant)
    draft = await _llm_voice_draft(facts, novel_name, team_id=team_id)
    wav_bytes = await _mimo_design_voice(draft)

    # 校验（与参考音频同一套规则：1-30 秒、<=15MB）后上传对象存储
    with tempfile.TemporaryDirectory(prefix="voice-design-") as temporary:
        sample = Path(temporary) / "sample.wav"
        sample.write_bytes(wav_bytes)
        duration = await _validate_audio_file(sample)
        key = make_upload_key(team_id, f"voice-design-{asset.canonical_name}.wav")
        await oss.put_file(key, sample, "audio/wav")

    # 与手动上传同格式：名称「角色名-项目名」（衍生形态加形态名），性别必填
    gender_label = _normalize_gender(facts["gender"], draft.gender, draft.voice_description)
    nickname = f"{asset.canonical_name}-{novel_name}" if novel_name else asset.canonical_name
    if variant:
        nickname = (
            f"{asset.canonical_name}·{variant.name}-{novel_name}"
            if novel_name
            else f"{asset.canonical_name}·{variant.name}"
        )
    reference = await _create_reference(
        nickname=nickname[:100],
        gender=gender_label,
        audio_url=key,
        duration=duration,
        team_id=team_id,
        created_by=created_by,
    )

    # 绑定：写回资产（或衍生形态）metadata，与前端手动选择音色的落库结构一致
    if variant is not None:
        metadata = _metadata_dict(variant.metadata)
        editor_form = _metadata_dict(metadata.get("editor_form"))
        variant.metadata = {
            **metadata,
            "voice": reference.nickname,
            "voice_reference_id": reference.id,
            "editor_form": {
                **editor_form,
                "voice": reference.nickname,
                "voice_reference_id": reference.id,
            },
        }
        await variant.save(update_fields=["metadata", "updated_at"])
    else:
        metadata = _metadata_dict(asset.metadata)
        asset.metadata = {
            **metadata,
            "voice": reference.nickname,
            "voice_reference_id": reference.id,
        }
        await asset.save(update_fields=["metadata", "updated_at"])
    return reference, asset, variant, draft
