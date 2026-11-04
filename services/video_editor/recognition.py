"""AI 语音识别生成智能字幕编排逻辑。"""
import logging
from uuid import uuid4
from fastapi import HTTPException

from auth.deps import AuthContext
from models.config import AiModelConfig
from models.video_edit import ChapterEditDraft
from schemas.video_edit import EditDocument, SubtitleClip
from services.audio_recognition.extractor import extract_timeline_audio
from services.audio_recognition.volc_seedasr import VolcSeedAsrClient
from services.billing.recorder import billing_recorder
from controllers.config import ai_model_config_controller
from services.balance import ensure_solvent
from services.video_editor.drafts import chapter_scope, initial_document
from services.video_editor.sources import EditSources
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message as msg

logger = logging.getLogger(__name__)


async def _resolve_asr_config(team_id: int | None) -> AiModelConfig:
    """Reuse the shared team/official model selection policy."""
    config = await ai_model_config_controller.get_active(AiTaskTypeEnum.audio_recognition.value, team_id=team_id)
    if not config.api_key:
        raise HTTPException(400, msg("请先配置语音识别模型的 API Key"))
    return config


async def recognize_and_apply_subtitles(
    chapter_id: int,
    ctx: AuthContext,
    client_document: EditDocument | None = None,
) -> dict:
    """从时间线视频提取原声音频，调用 ASR 识别并生成字幕片段。

    - 自动清空已有字幕片段；
    - 生成一段一段与发音时间对齐的字幕片段；
    - 返回待应用结果，由编辑器通过现有草稿保存流程持久化；
    - 记录 ASR 计费。
    """
    chapter = await chapter_scope(chapter_id, ctx, write=True)

    # 1. 确定当前工作时间线文档
    draft = await ChapterEditDraft.get_or_none(chapter_id=chapter.id)
    if client_document is not None:
        document = client_document.model_copy(deep=True)
    elif draft is not None:
        document = EditDocument.model_validate(draft.document)
    else:
        resolver = EditSources(chapter.novel_id, chapter.id)
        catalog = await resolver.catalog()
        document = await initial_document(chapter, catalog)

    # 2. 匹配已启用的语音识别模型
    config = await _resolve_asr_config(ctx.team_id)

    # Use the existing balance and member-limit preflight.
    if config.scope != "team":
        await ensure_solvent(ctx.team_id, ctx.user.id if ctx.user else None)

    # 4. 提取时间线主轨音频
    audio_bytes, duration = await extract_timeline_audio(
        document=document,
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
    )

    # 5. 调用火山引擎录音文件识别 API
    client = VolcSeedAsrClient(
        api_key=config.api_key,
        base_url=config.base_url or "https://openspeech.bytedance.com/api/v3/auc/bigmodel",
        model=config.model or "volc.seedasr.auc",
    )
    try:
        utterances = await client.recognize(audio_bytes=audio_bytes, format="mp3")
    except Exception as exc:
        logger.warning("asr recognition failed chapter_id=%d error_type=%s", chapter.id, type(exc).__name__)
        raise HTTPException(502, msg("语音识别服务处理异常，请稍后重试")) from None

    # 6. 将分句转换为 SubtitleClip，并清洗文本末尾标点
    new_subtitles: list[SubtitleClip] = []
    fps = document.fps or 24
    for item in utterances:
        raw_text = (item.get("text") or "").strip()
        clean_text = raw_text.rstrip("，。！？,.!? \t\r\n")
        if not clean_text:
            continue
        start_sec = max(0.0, float(item.get("start_time", 0)) / 1000.0)
        end_sec = max(start_sec + 0.1, float(item.get("end_time", 0)) / 1000.0)
        dur = max(1.0 / fps, end_sec - start_sec)

        new_subtitles.append(
            SubtitleClip(
                id=uuid4().hex,
                type="subtitle",
                name="",
                start=round(start_sec, 3),
                duration=round(dur, 3),
                text=clean_text,
                font="sans",
                font_size=42,
                color="#ffffff",
                stroke_color="#000000",
                stroke_width=2.0,
                shadow=1.0,
                bottom=10.0,
                align="center",
            )
        )

    # 7. 同时清空已有字幕，并追加生成的一段一段字幕
    non_subtitle_clips = [c for c in document.clips if c.type != "subtitle"]
    if new_subtitles:
        document.clips = non_subtitle_clips + new_subtitles

    # 9. 记录用量流水并扣除团队余额
    record = await billing_recorder.record_asr(
        novel_id=chapter.novel_id,
        seconds=duration,
        model_config_id=config.id,
        config_snapshot=config,
        fallback_model=config.model,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    if record and record.cost_source != "team_key" and ctx.team_id:
        from services.balance import accumulate_member_cost, consume
        await consume(ctx.team_id, record.cost, usage_record_id=record.id)
        await accumulate_member_cost(ctx.team_id, ctx.user.id if ctx.user else None, record.cost)

    return {
        "document": document.model_dump(mode="json"),
        "subtitles_created": len(new_subtitles),
        "revision": draft.revision if draft else 0,
    }
