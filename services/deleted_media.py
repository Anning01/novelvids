"""Retry deletion of managed files after the database change commits."""

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tortoise.timezone import now

from config import settings
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter_export import ChapterExport
from models.digital_human import DigitalHuman
from models.media_deletion import MediaDeletion
from models.novel import Novel
from models.remake_source import RemakeSource
from models.remake_upload import RemakeUpload
from models.resource_library import VideoResource
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterCanvasSnapshot, ChapterEditDraft, EditorAsset
from services.cover_derivatives import image_derivative_reference, local_media_path
from services.oss import normalize_media_url, oss
from services.video.poster import video_poster_reference

logger = logging.getLogger(__name__)

# Include archived rows since their media may still be used on restoration.
MEDIA_FIELDS = {
    Novel: ("cover",),
    Asset: ("main_image", "angle_image_1", "angle_image_2", "metadata"),
    AssetVariant: ("images", "metadata"),
    Scene: ("metadata", "prompt_params"),
    Video: ("url", "metadata"),
    ChapterExport: ("media_ref", "source_media_ref", "manifest"),
    ChapterCanvasSnapshot: ("layout",),
    ChapterEditDraft: ("document",),
    EditorAsset: ("media_ref", "poster_ref"),
    VideoResource: ("storage_ref", "poster_ref"),
    AudioReference: ("audio_url", "avatar_url"),
    DigitalHuman: ("image_url",),
    RemakeSource: ("object_key", "source_video_manifest"),
    RemakeUpload: ("object_key",),
    AiTask: ("response_data",),
}


def media_refs(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from media_refs(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from media_refs(item)
    elif isinstance(value, str):
        raw = normalize_media_url(value) or value
        if raw.startswith(("./media/", "media/")):
            raw = "/" + raw.removeprefix("./")
        raw = unquote(urlsplit(raw).path) if raw.startswith(("/media/", "uploads/", "remake/")) else ""
        if raw and ".." not in raw.split("/") and "\\" not in raw and len(raw) <= 1000:
            yield raw


def derivatives(ref):
    for kind in ("thumbnail", "preview"):
        for reference in (image_derivative_reference(ref, kind), video_poster_reference(ref, kind)):
            if reference:
                yield reference


async def enqueue_media(values, team_id, *, asset_id=None, video_ids=()):
    generated_names = [rf"asset-{asset_id}(?:_[\w-]*)?\.[a-z]+"] if asset_id is not None else []
    generated_names.extend(rf"(?:{identifier}\.mp4|last-frame-{identifier}\.png)" for identifier in video_ids)
    generated = re.compile(r"uploads/0/\d{8}/[0-9a-f]{12}-(?:" + "|".join(generated_names) + ")") if generated_names else None
    refs = {ref for ref in media_refs(values)
            if ref.startswith(("/media/", f"uploads/{team_id or 0}/", f"remake/sources/{team_id or 0}/",
                               f"remake/sources/history/{team_id or 0}/"))
            or (generated is not None and generated.fullmatch(ref))}
    refs.update(derivative for ref in tuple(refs) for derivative in derivatives(ref))
    await MediaDeletion.bulk_create([MediaDeletion(reference=ref) for ref in refs], ignore_conflicts=True)


async def drain_media_deletions():
    pending = await MediaDeletion.all().order_by("updated_at", "id").limit(50)
    if not pending:
        return
    unused = {row.reference for row in pending}
    for model, columns in MEDIA_FIELDS.items():
        query = model.with_deleted() if hasattr(model, "with_deleted") else model.all()
        for row in await query.values_list(*columns):
            for ref in media_refs(row):
                unused.discard(ref)
                if ref.startswith("remake/"):
                    unused.discard(f"/media/{ref}")
                unused.difference_update(derivatives(ref))
        if not unused:
            break
    for row in pending:
        try:
            ref = row.reference
            if ref in unused:
                if ref.startswith("/media/exports/"):
                    from services.video_enhancement.media import export_media
                    root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
                    relative = ref.removeprefix("/media/exports/")
                    path = export_media.local_path(ref)
                else:
                    root = Path(settings.MEDIA_PATH).resolve()
                    relative = ref.removeprefix("/media/")
                    path = local_media_path(root, ref)
                if path is not None and path == root / relative:
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                elif oss.enabled and ref.startswith(("uploads/", "remake/")):
                    await oss.delete(ref)
                elif ref.startswith(("uploads/", "remake/")):
                    await MediaDeletion.filter(id=row.id).update(updated_at=now())
                    continue
            await row.delete()
        except Exception:
            logger.warning("Could not clean deleted media job %s", row.id)
            await MediaDeletion.filter(id=row.id).update(updated_at=now())


async def clean_deleted_media_periodically():
    while True:
        try:
            await drain_media_deletions()
        except Exception:
            logger.warning("Could not process the media cleanup queue")
        await asyncio.sleep(30)
