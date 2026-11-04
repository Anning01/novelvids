"""Deterministic export jobs use AiTask status and scoped ChapterExport downloads."""
import asyncio
import logging
import shutil
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from fastapi import HTTPException
from tortoise.expressions import Q
from config import settings
from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.video_edit import ChapterEditDraft
from schemas.video_edit import EditDocument
from services.creation_objects import project_write
from services.video_editor.assets import editor_storage
from services.video_editor.drafts import chapter_scope
from services.video_editor.sources import EditSources
from services.video_editor.render import EditRenderer
from services.video_enhancement.media import digest, export_media, file_digest, inspect_media
from utils.messages import localized_message as msg

logger = logging.getLogger(__name__)


async def describe_export(row):
    task = await AiTask.get(id=row.task_id)
    return {'id': row.id, 'task_id': str(task.id), 'status': task.status, 'stage': task.stage,
            'progress': task.progress, 'error': task.error_message,
            'revision': row.recipe.get('revision'), 'created_at': row.created_at.isoformat(),
            'url': f'/api/video/exports/{row.id}/download' if row.media_ref else None}


async def submit_export(chapter_id, revision, ctx):
    chapter = await chapter_scope(chapter_id, ctx, write=True)
    draft = await ChapterEditDraft.get_or_none(chapter_id=chapter_id)
    if not draft or draft.revision != revision:
        raise HTTPException(409, msg('请先保存当前剪辑草稿后再导出'))
    document = EditDocument.model_validate(draft.document)
    if not document.clips:
        raise HTTPException(422, msg('时间线没有可导出的片段'))
    manifest = await EditSources(chapter.novel_id, chapter.id).validate(document)
    if any(item.get('missing') for item in manifest):
        raise HTTPException(422, msg('时间线仍有未生成或失效的视频，请先补全或移除对应片段'))
    manifest = [{key: value for key, value in row.items() if key not in {'url', 'poster'}} for row in manifest]
    identity = digest(['editor-render-v1', chapter.novel_id, chapter.id, draft.document,
                       [(row['key'], row['ref'], row.get('sha256')) for row in manifest]])
    async with project_write(chapter.novel_id) as db:
        current = await ChapterEditDraft.filter(id=draft.id).using_db(db).get()
        if current.revision != revision:
            raise HTTPException(409, msg('请先保存当前剪辑草稿后再导出'))
        existing = await ChapterExport.get_or_none(identity_key=identity).using_db(db)
        if existing:
            task = await AiTask.get(id=existing.task_id).using_db(db)
            if task.status in {4, 5}:
                await AiTask.filter(id=task.id).using_db(db).update(status=6, stage='editor_queued',
                    error_message=None, finished_at=None, started_at=None, progress=0)
            return existing
        row = await ChapterExport.create(novel_id=chapter.novel_id, chapter_id=chapter.id,
            team_id=ctx.team_id, created_by=ctx.user.id if ctx.user else None, identity_key=identity,
            source_version=digest(draft.document), manifest=manifest,
            recipe={'kind': 'editor_render', 'version': 1, 'revision': revision, 'document': draft.document}, using_db=db)
        task = await AiTask.create(task_type=4, status=6, stage='editor_queued', request_params={
            'operation': 'editor_render', 'editor_version': 1, 'export_id': row.id, 'novel_id': chapter.novel_id,
            'chapter_id': chapter.id, 'team_id': ctx.team_id, 'user_id': ctx.user.id if ctx.user else None}, using_db=db)
        row.task_id = task.id
        await row.save(using_db=db, update_fields=['task_id'])
    return row


class EditorExportWorker:
    """One local encoder; a DB lease makes restarts and duplicate dispatch safe."""
    def __init__(self):
        self.loop_task = None
        self.active = None

    async def start(self):
        self.loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.loop_task:
            self.loop_task.cancel()
            await asyncio.gather(self.loop_task, return_exceptions=True)
        if self.active:
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)
        self.loop_task = self.active = None

    async def loop(self):
        while True:
            try:
                if self.active and self.active.done():
                    if not self.active.cancelled():
                        self.active.result()
                    self.active = None
                if not self.active:
                    row = await ChapterExport.filter(task__stage__startswith='editor_',
                        task__status__in=[1, 2, 6]).order_by('id').first()
                    if row:
                        self.active = asyncio.create_task(self.execute(row.id))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning('Editor dispatch deferred: error_type=%s', type(error).__name__)
                self.active = None
            await asyncio.sleep(1)

    async def execute(self, export_id):
        row = await ChapterExport.get(id=export_id)
        owner, now = uuid4(), datetime.now(timezone.utc)
        claimed = await ChapterExport.filter(Q(collection_lease_until__isnull=True) | Q(collection_lease_until__lt=now),
            id=row.id).update(collection_owner=owner, collection_lease_until=now + timedelta(seconds=30))
        if not claimed:
            return
        task = await AiTask.get(id=row.task_id)

        async def cancelled():
            return not await AiTask.filter(id=task.id, status=2).exists()

        async def progress(percent, stage):
            await AiTask.filter(id=task.id, status=2).update(progress=percent, stage=stage)

        async def renewal():
            while True:
                await asyncio.sleep(5)
                updated = await ChapterExport.filter(id=row.id, collection_owner=owner).update(
                    collection_lease_until=datetime.now(timezone.utc) + timedelta(seconds=30))
                if not updated:
                    raise RuntimeError('Editor lease lost')

        heartbeat = None
        work = None
        try:
            if task.status not in {1, 2, 6}:
                return
            from services.creation_agent.handler import authorize_run
            await authorize_run(task.request_params)
            from services.video_enhancement.sources import require_generation_scope
            await require_generation_scope(row.novel_id, task.request_params.get('team_id'))
            await AiTask.filter(id=task.id, status__in=[1, 2, 6]).update(status=2, stage='editor_checking',
                started_at=now, error_message=None)
            heartbeat = asyncio.create_task(renewal())
            work = asyncio.create_task(self.render(row, cancelled, progress))
            done, _ = await asyncio.wait({work, heartbeat}, timeout=settings.VIDEO_EDITOR_RENDER_TIMEOUT,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError
            if heartbeat in done:
                heartbeat.result()
            result = await work
            await AiTask.filter(id=task.id, status=2).update(status=3, stage='completed', progress=100,
                response_data=result, finished_at=datetime.now(timezone.utc), error_message=None)
        except asyncio.CancelledError:
            await AiTask.filter(id=task.id, status=2).update(status=6, stage='editor_queued')
            raise
        except Exception as error:
            logger.warning('Editor render failed: export_id=%s error_type=%s', row.id, type(error).__name__)
            detail = error.detail if isinstance(error, HTTPException) else str(error) if isinstance(error, ValueError) else msg('成片渲染未完成，请重试或检查素材')
            await AiTask.filter(id=task.id, status__in=[1, 2, 6]).update(status=4, stage='editor_failed',
                error_message=detail, finished_at=datetime.now(timezone.utc))
        finally:
            for job in (work, heartbeat):
                if job:
                    job.cancel()
            await asyncio.gather(*(job for job in (work, heartbeat) if job), return_exceptions=True)
            await ChapterExport.filter(id=row.id, collection_owner=owner).update(collection_owner=None, collection_lease_until=None)

    async def render(self, row, cancelled, progress):
        document = EditDocument.model_validate(row.recipe['document'])
        if not all(item.get('sha256') for item in row.manifest):
            frozen = await EditSources(row.novel_id, row.chapter_id).validate(document, freeze=True)
            admitted = {item['key']: item['ref'] for item in row.manifest}
            if any(admitted.get(item['key']) != item['ref'] for item in frozen):
                raise ValueError(msg('剪辑素材内容已变化，请重新读取'))
            row.manifest = [{key: value for key, value in item.items() if key not in {'url', 'poster'}} for item in frozen]
            await row.save(update_fields=['manifest'])
        root = Path(settings.CHAPTER_EXPORT_PATH).resolve()
        root.mkdir(parents=True, exist_ok=True)
        async with AsyncExitStack() as stack:
            sources = {}
            total_bytes = 0
            for item in row.manifest:
                if await cancelled():
                    raise asyncio.CancelledError
                path = await stack.enter_async_context(editor_storage.materialize(item['ref']))
                total_bytes += path.stat().st_size
                if total_bytes > settings.VIDEO_EDITOR_MAX_SOURCE_MB * 1024 * 1024:
                    raise ValueError(msg('本次导出的素材总大小超过服务端限制'))
                if shutil.disk_usage(root).free < 256 * 1024 * 1024:
                    raise ValueError(msg('服务器磁盘空间不足，无法导出成片'))
                if await asyncio.to_thread(file_digest, path) != item['sha256']:
                    raise ValueError(msg('剪辑素材内容已变化，请重新读取'))
                sources[item['key']] = (path, item)
            with TemporaryDirectory(dir=root, prefix='.editor-render-') as directory:
                renderer = EditRenderer(cancelled=cancelled, progress=progress)
                output = await renderer.render(document, sources, Path(directory))
                ref = export_media.ref(row, 'edited')
                sha = await asyncio.to_thread(file_digest, output)
                probe = await asyncio.to_thread(inspect_media, output)
                if await cancelled():
                    raise asyncio.CancelledError
                await export_media.store(ref, output)
                row.media_ref, row.media_sha256, row.output_probe = ref, sha, probe.model_dump(mode='json')
                row.collection_complete = True
                await row.save(update_fields=['media_ref', 'media_sha256', 'output_probe', 'collection_complete', 'updated_at'])
        return {'export_id': row.id, 'duration': float(probe.duration)}


editor_export_worker = EditorExportWorker()
