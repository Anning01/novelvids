from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from exceptions.remake import RemakeError
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from schemas.remake import RemakeProjectCreate
from services.balance import ensure_solvent
from services.project_config import validate_project_config
from services.remake.episodes import validate_episode_batch
from services.remake.uploads import RemakeUploadService, remake_upload_service
from services.remake.history_snapshot import (
    RemakeHistorySnapshotService,
    remake_history_snapshot_service,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, WorkflowStatus

logger = logging.getLogger(__name__)


class RemakeProjectService:
    """幂等创建项目、章节、不可变来源和拆解任务的事务编排器。"""

    def __init__(
        self,
        *,
        upload_service: RemakeUploadService | None = None,
        history_snapshot_service: RemakeHistorySnapshotService | None = None,
        balance_checker=ensure_solvent,
    ) -> None:
        self.upload_service = upload_service or remake_upload_service
        self.history_snapshot_service = (
            history_snapshot_service or remake_history_snapshot_service
        )
        self.balance_checker = balance_checker
        self._locks: dict[str, asyncio.Lock] = {}
        self._retry_locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _payload_hash(payload: RemakeProjectCreate) -> str:
        normalized = payload.model_dump(mode="json", exclude={"idempotency_key"})
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def create(
        self,
        payload: RemakeProjectCreate,
        *,
        team_id: int | None,
        user_id: int | None,
        allow_all_history: bool = False,
    ) -> dict:
        key = str(payload.idempotency_key)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                return await self._create_locked(
                    payload,
                    team_id=team_id,
                    user_id=user_id,
                    allow_all_history=allow_all_history,
                )
        finally:
            if not lock.locked():
                self._locks.pop(key, None)

    async def _create_locked(
        self,
        payload: RemakeProjectCreate,
        *,
        team_id: int | None,
        user_id: int | None,
        allow_all_history: bool,
    ) -> dict:
        payload_hash = self._payload_hash(payload)
        existing = await Novel.get_or_none(creation_idempotency_key=str(payload.idempotency_key))
        if existing is not None:
            return await self._existing_result(
                existing,
                payload_hash=payload_hash,
                team_id=team_id,
                user_id=user_id,
            )

        if not payload.sources:
            raise RemakeError(
                422,
                "REMAKE_SOURCE_MODE_MISMATCH",
                "至少需要一个来源视频",
            )
        if payload.style_key and payload.custom_style_prompt and payload.custom_style_prompt.strip():
            raise RemakeError(
                422,
                "REMAKE_PROJECT_CONFIG_INVALID",
                "系统风格与自定义风格只能选择一种",
            )
        try:
            project_config = validate_project_config(
                {
                    "aspect_ratio": payload.aspect_ratio,
                    "resolution": payload.resolution,
                    "style_key": payload.style_key,
                    "custom_style_prompt": payload.custom_style_prompt,
                }
            )
        except Exception as error:
            detail = getattr(error, "detail", "项目配置无效")
            raise RemakeError(422, "REMAKE_PROJECT_CONFIG_INVALID", str(detail)) from error

        await self.balance_checker(team_id, user_id)
        prepared, warnings = await self._prepare_sources(
            payload,
            team_id=team_id,
            user_id=user_id,
            allow_all_history=allow_all_history,
        )
        descriptions = {
            "single_upload": "重制工坊 · 单视频",
            "folder_upload": "重制工坊 · 文件夹多集",
            "history": "重制工坊 · 历史项目",
        }
        created: list[tuple[RemakeSource, AiTask]] = []

        try:
            for item in prepared:
                upload = item["upload"]
                if upload is None:
                    continue
                promotion = await self.upload_service.promote_local(upload)
                item["promotion"] = promotion
                if promotion is not None:
                    item["object_key"] = promotion[1]
            async with in_transaction() as connection:
                novel = await Novel.create(
                    using_db=connection,
                    name=payload.name.strip(),
                    author="重制工坊",
                    description=descriptions[payload.source_mode],
                    content="",
                    total_chapters=len(prepared),
                    workflow_kind="remake",
                    aspect_ratio=project_config["aspect_ratio"],
                    resolution=project_config["resolution"],
                    style_key=project_config.get("style_key"),
                    custom_style_prompt=project_config.get("custom_style_prompt"),
                    creation_idempotency_key=str(payload.idempotency_key),
                    creation_payload_hash=payload_hash,
                    team_id=team_id,
                    created_by=user_id,
                )
                for item in prepared:
                    episode_number = item["episode_number"]
                    media = item["media"]
                    chapter = await Chapter.create(
                        using_db=connection,
                        novel=novel,
                        number=episode_number,
                        name=f"第{episode_number}集",
                        content="",
                        status=TaskStatusEnum.pending.value,
                        workflow_status=WorkflowStatus.draft.value,
                    )
                    source = await RemakeSource.create(
                        using_db=connection,
                        novel=novel,
                        chapter=chapter,
                        episode_number=episode_number,
                        source_kind=item["source_kind"],
                        storage_provider=item["storage_provider"],
                        object_key=item["object_key"],
                        original_filename=media.original_filename,
                        mime_type=media.mime_type,
                        size_bytes=media.size_bytes,
                        duration_seconds=media.duration_seconds,
                        width=media.width,
                        height=media.height,
                        container_format=media.container_format,
                        checksum=media.checksum,
                        source_novel_id=item["source_novel_id"],
                        source_chapter_id=item["source_chapter_id"],
                        source_video_manifest=item["source_video_manifest"],
                        media_status="ready",
                        team_id=team_id,
                        created_by=user_id,
                    )
                    task = await AiTask.create(
                        using_db=connection,
                        task_type=AiTaskTypeEnum.remake_decomposition.value,
                        status=TaskStatusEnum.queued.value,
                        stage="queued",
                        progress=0,
                        request_params={
                            "novel_id": novel.id,
                            "chapter_id": chapter.id,
                            "remake_source_id": source.id,
                            "team_id": team_id,
                            "user_id": user_id,
                            "attempt": 1,
                        },
                    )
                    task.request_params = {
                        **task.request_params,
                        "ai_task_id": str(task.id),
                    }
                    await task.save(
                        using_db=connection,
                        update_fields=["request_params", "updated_at"],
                    )
                    source.analysis_task_id = task.id
                    await source.save(
                        using_db=connection,
                        update_fields=["analysis_task_id", "updated_at"],
                    )
                    upload = item["upload"]
                    if upload is not None:
                        upload.object_key = item["object_key"]
                        upload.status = "committed"
                        upload.committed_at = datetime.now(timezone.utc)
                        await upload.save(
                            using_db=connection,
                            update_fields=["object_key", "status", "committed_at", "updated_at"],
                        )
                    created.append((source, task))
        except IntegrityError as error:
            await self._rollback_prepared(prepared)
            existing = await Novel.get_or_none(
                creation_idempotency_key=str(payload.idempotency_key)
            )
            if existing is not None:
                return await self._existing_result(
                    existing,
                    payload_hash=payload_hash,
                    team_id=team_id,
                    user_id=user_id,
                )
            raise RemakeError(409, "REMAKE_PROJECT_CONFIG_INVALID", "项目名称已存在") from error
        except Exception:
            await self._rollback_prepared(prepared)
            raise
        return self._result(novel, created, warnings)

    async def _prepare_sources(
        self,
        payload: RemakeProjectCreate,
        *,
        team_id: int | None,
        user_id: int | None,
        allow_all_history: bool,
    ) -> tuple[list[dict], list[dict]]:
        if payload.source_mode == "single_upload":
            if len(payload.sources) != 1:
                raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "单视频模式只能选择一个来源")
            source_input = payload.sources[0]
            if source_input.episode_number != 1 or source_input.upload_token is None or source_input.source_chapter_id is not None:
                raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "单视频来源必须使用上传 token 并创建为第1集")
            upload = await self.upload_service.get_ready(source_input.upload_token, team_id=team_id, user_id=user_id)
            media = await self.upload_service.revalidate(upload)
            return [self._upload_item(upload, media, 1)], []

        if payload.source_mode == "folder_upload":
            uploads = []
            seen_tokens = set()
            for source_input in payload.sources:
                if source_input.episode_number is None or source_input.upload_token is None or source_input.source_chapter_id is not None:
                    raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "文件夹来源必须提交集数和上传 token")
                if source_input.upload_token in seen_tokens:
                    raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "同一上传 token 不能重复使用")
                seen_tokens.add(source_input.upload_token)
                upload = await self.upload_service.get_ready(source_input.upload_token, team_id=team_id, user_id=user_id)
                uploads.append((upload.original_filename, source_input.episode_number, (upload, source_input)))
            batch, missing = validate_episode_batch(uploads)
            prepared = []
            for item in batch:
                upload, _ = item.value
                media = await self.upload_service.revalidate(upload)
                prepared.append(self._upload_item(upload, media, item.episode_number))
            warnings = ([{"code": "REMAKE_EPISODE_GAPS", "missing_episode_numbers": missing}] if missing else [])
            return prepared, warnings

        if payload.source_mode != "history" or len(payload.sources) != 1:
            raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "当前历史模式只能选择一个来源章节")
        source_input = payload.sources[0]
        if source_input.episode_number is not None or source_input.upload_token is not None or source_input.source_chapter_id is None:
            raise RemakeError(422, "REMAKE_SOURCE_MODE_MISMATCH", "历史项目来源只能提交来源章节 ID")
        historical_chapter = await Chapter.get_or_none(id=source_input.source_chapter_id).select_related("novel")
        if historical_chapter is None:
            raise RemakeError(422, "REMAKE_HISTORY_EPISODE_UNAVAILABLE", "历史剧集不存在或暂不可重制")
        if historical_chapter.novel.workflow_kind != "script":
            raise RemakeError(
                422,
                "REMAKE_HISTORY_EPISODE_UNAVAILABLE",
                "历史来源只能选择短剧制作中的剧集",
            )
        if not allow_all_history and historical_chapter.novel.team_id != team_id:
            raise RemakeError(403, "REMAKE_HISTORY_PROJECT_FORBIDDEN", "无权使用该历史项目")
        snapshot = await self.history_snapshot_service.create(historical_chapter, team_id=team_id)
        return [{
            "episode_number": historical_chapter.number,
            "source_kind": "history",
            "storage_provider": snapshot.storage_provider,
            "object_key": snapshot.object_key,
            "media": snapshot.media,
            "source_novel_id": snapshot.source_novel_id,
            "source_chapter_id": snapshot.source_chapter_id,
            "source_video_manifest": snapshot.manifest,
            "upload": None,
            "promotion": None,
            "snapshot": snapshot,
        }], []

    @staticmethod
    def _upload_item(upload, media, episode_number: int) -> dict:
        return {
            "episode_number": episode_number,
            "source_kind": "upload",
            "storage_provider": "local" if upload.storage_provider == "local" else "oss",
            "object_key": upload.object_key,
            "media": media,
            "source_novel_id": None,
            "source_chapter_id": None,
            "source_video_manifest": {},
            "upload": upload,
            "promotion": None,
            "snapshot": None,
        }

    async def _rollback_prepared(self, prepared: list[dict]) -> None:
        for item in reversed(prepared):
            try:
                await self.upload_service.rollback_promotion(item.get("promotion"))
            except Exception:
                logger.exception("Failed to roll back a remake upload promotion")
            snapshot = item.get("snapshot")
            if snapshot is not None:
                try:
                    await self.history_snapshot_service.cleanup(snapshot)
                except Exception:
                    logger.exception("Failed to clean up a remake history snapshot")

    async def retry(
        self,
        source_id: int,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> dict:
        lock = self._retry_locks.setdefault(source_id, asyncio.Lock())
        try:
            async with lock:
                return await self._retry_locked(
                    source_id,
                    team_id=team_id,
                    user_id=user_id,
                )
        finally:
            if not lock.locked():
                self._retry_locks.pop(source_id, None)

    async def _retry_locked(
        self,
        source_id: int,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> dict:
        await self.balance_checker(team_id, user_id)
        async with in_transaction() as connection:
            source = await RemakeSource.filter(id=source_id).using_db(connection).select_for_update().first()
            if (
                source is None
                or source.team_id != team_id
                or source.created_by != user_id
            ):
                raise RemakeError(
                    404,
                    "REMAKE_SOURCE_NOT_FOUND",
                    "重制来源不存在",
                )
            previous = None
            if source.analysis_task_id is not None:
                previous = await AiTask.get_or_none(
                    id=source.analysis_task_id
                ).using_db(connection)
            if (
                source.media_status != "failed"
                or previous is None
                or previous.status != TaskStatusEnum.failed.value
            ):
                raise RemakeError(
                    409,
                    "REMAKE_ANALYSIS_NOT_RETRYABLE",
                    "只有失败的拆解任务可以重试",
                )
            previous_params = previous.request_params or {}
            attempt = max(1, int(previous_params.get("attempt", 1) or 1)) + 1
            task = await AiTask.create(
                using_db=connection,
                task_type=AiTaskTypeEnum.remake_decomposition.value,
                status=TaskStatusEnum.queued.value,
                stage="queued",
                progress=0,
                request_params={
                    "novel_id": source.novel_id,
                    "chapter_id": source.chapter_id,
                    "remake_source_id": source.id,
                    "team_id": team_id,
                    "user_id": user_id,
                    "attempt": attempt,
                    "retry_of_task_id": str(previous.id),
                },
            )
            task.request_params = {
                **task.request_params,
                "ai_task_id": str(task.id),
            }
            await task.save(
                using_db=connection,
                update_fields=["request_params", "updated_at"],
            )
            source.analysis_task_id = task.id
            source.media_status = "ready"
            await source.save(
                using_db=connection,
                update_fields=["analysis_task_id", "media_status", "updated_at"],
            )
        return {
            "source_id": source.id,
            "task_id": task.id,
            "status": "queued",
            "attempt": attempt,
        }

    async def _existing_result(
        self,
        novel: Novel,
        *,
        payload_hash: str,
        team_id: int | None,
        user_id: int | None,
    ) -> dict:
        if (
            novel.creation_payload_hash != payload_hash
            or novel.team_id != team_id
            or novel.created_by != user_id
        ):
            raise RemakeError(
                409,
                "REMAKE_IDEMPOTENCY_CONFLICT",
                "相同幂等键已经用于不同的创建请求",
            )
        sources = await RemakeSource.filter(novel=novel).order_by(
            "episode_number", "id"
        ).select_related("analysis_task")
        created = [
            (source, source.analysis_task)
            for source in sources
            if source.analysis_task is not None
        ]
        return self._result(novel, created, self._gap_warnings(sources))

    @staticmethod
    def _gap_warnings(sources: list[RemakeSource]) -> list[dict]:
        numbers = sorted(source.episode_number for source in sources)
        if not numbers:
            return []
        present = set(numbers)
        missing = [number for number in range(numbers[0], numbers[-1] + 1) if number not in present]
        return ([{"code": "REMAKE_EPISODE_GAPS", "missing_episode_numbers": missing}] if missing else [])

    @staticmethod
    def _result(
        novel: Novel,
        created: list[tuple[RemakeSource, AiTask]],
        warnings: list[dict],
    ) -> dict:
        return {
            "novel_id": novel.id,
            "workflow_kind": novel.workflow_kind,
            "entry_path": f"/create/remake/{novel.id}/progress",
            "sources": [
                {
                    "source_id": source.id,
                    "chapter_id": source.chapter_id,
                    "episode_number": source.episode_number,
                    "task_id": task.id,
                    "status": task.stage or "queued",
                }
                for source, task in created
            ],
            "warnings": warnings,
        }


remake_project_service = RemakeProjectService()
