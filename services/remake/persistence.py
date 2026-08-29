"""重制拆解结果到通用资产、分镜模型的事务持久化。"""

from __future__ import annotations

from typing import Any

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from models.asset import Asset
from models.chapter import Chapter
from models.remake_source import RemakeSource
from models.scene import Scene
from utils.enums import AssetTypeEnum, TaskStatusEnum, WorkflowStatus


class RemakePersistenceError(RuntimeError):
    pass


_ASSET_GROUPS = (
    ("characters", AssetTypeEnum.person),
    ("scenes", AssetTypeEnum.scene),
    ("objects", AssetTypeEnum.item),
)


class RemakeResultPersistence:
    async def persist(
        self,
        *,
        source: RemakeSource,
        assets: dict[str, list[dict[str, Any]]],
        prompt_document: dict[str, Any],
        pipeline_metadata: dict[str, Any],
    ) -> dict[str, int]:
        prompts = [
            item
            for item in prompt_document.get("prompts", [])
            if isinstance(item, dict)
        ]
        async with in_transaction() as connection:
            asset_index = await self._persist_assets(
                connection,
                source=source,
                assets=assets,
            )
            scene_count = await self._persist_scenes(
                connection,
                source=source,
                prompts=prompts,
                asset_index=asset_index,
                pipeline_metadata=pipeline_metadata,
            )
            await Chapter.filter(id=source.chapter_id).using_db(connection).update(
                status=TaskStatusEnum.completed.value,
                workflow_status=WorkflowStatus.storyboard_ready.value,
            )
            await RemakeSource.filter(id=source.id).using_db(connection).update(
                media_status="completed"
            )
        source.media_status = "completed"
        return {"asset_count": len(asset_index), "scene_count": scene_count}

    async def _persist_assets(
        self,
        connection: BaseDBAsyncClient,
        *,
        source: RemakeSource,
        assets: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Asset]:
        result: dict[str, Asset] = {}
        chapter = await Chapter.get(id=source.chapter_id).using_db(connection)
        for group, asset_type in _ASSET_GROUPS:
            for item in assets.get(group, []):
                if not isinstance(item, dict):
                    continue
                reference_id = str(item.get("id", "")).strip()
                name = str(item.get("name", "")).strip()
                if not reference_id or not name:
                    continue
                existing = await Asset.get_or_none(
                    novel_id=source.novel_id,
                    asset_type=asset_type.value,
                    canonical_name=name,
                ).using_db(connection)
                if existing is None:
                    existing = await Asset.create(
                        using_db=connection,
                        novel_id=source.novel_id,
                        asset_type=asset_type.value,
                        canonical_name=name,
                        aliases=[],
                        description=str(item.get("description", "")).strip(),
                        base_traits=str(item.get("description", "")).strip(),
                        is_global=True,
                        source_chapters=[chapter.number],
                        last_updated_chapter=chapter.number,
                        metadata={
                            "analysis_source": "remake_decomposition",
                            "remake_source_id": source.id,
                            "remake_source_ids": [source.id],
                            "remake_reference_id": reference_id,
                            "remake_label": str(item.get("label", "")),
                        },
                    )
                else:
                    metadata = existing.metadata if isinstance(existing.metadata, dict) else {}
                    raw_source_ids = metadata.get("remake_source_ids")
                    source_ids = [
                        int(value)
                        for value in (raw_source_ids if isinstance(raw_source_ids, list) else [])
                        if isinstance(value, int)
                    ]
                    legacy_source_id = metadata.get("remake_source_id")
                    if isinstance(legacy_source_id, int) and legacy_source_id not in source_ids:
                        source_ids.append(legacy_source_id)
                    if source.id not in source_ids:
                        source_ids.append(source.id)
                        source_ids.sort()
                    owned = (
                        metadata.get("analysis_source") == "remake_decomposition"
                        and legacy_source_id == source.id
                    )
                    chapters = list(existing.source_chapters or [])
                    if chapter.number not in chapters:
                        chapters.append(chapter.number)
                        chapters.sort()
                    existing.source_chapters = chapters
                    if owned:
                        description = str(item.get("description", "")).strip()
                        existing.description = description
                        existing.base_traits = description
                        existing.last_updated_chapter = chapter.number
                        existing.metadata = {
                            **metadata,
                            "remake_source_ids": source_ids,
                            "remake_reference_id": reference_id,
                            "remake_label": str(item.get("label", "")),
                        }
                        update_fields = [
                            "description",
                            "base_traits",
                            "source_chapters",
                            "last_updated_chapter",
                            "metadata",
                            "updated_at",
                        ]
                    else:
                        existing.metadata = {
                            **metadata,
                            "remake_source_ids": source_ids,
                        }
                        update_fields = ["source_chapters", "metadata", "updated_at"]
                    await existing.save(using_db=connection, update_fields=update_fields)
                result[reference_id] = existing
        return result

    async def _persist_scenes(
        self,
        connection: BaseDBAsyncClient,
        *,
        source: RemakeSource,
        prompts: list[dict[str, Any]],
        asset_index: dict[str, Asset],
        pipeline_metadata: dict[str, Any],
    ) -> int:
        sequences: set[int] = set()
        for position, item in enumerate(prompts, start=1):
            sequence = _positive_int(item.get("shot_index"), position)
            sequences.add(sequence)
            scene = await Scene.get_or_none(
                chapter_id=source.chapter_id,
                sequence=sequence,
            ).using_db(connection)
            metadata = scene.metadata if scene and isinstance(scene.metadata, dict) else {}
            if scene is not None and metadata.get("remake_source_id") != source.id:
                raise RemakePersistenceError(
                    f"第 {sequence} 个分镜已存在，无法覆盖非重制生成内容"
                )
            scene_metadata = {
                **metadata,
                "analysis_source": "remake_decomposition",
                "remake_source_id": source.id,
                "source_file": str(item.get("file", "")),
                "confidence": item.get("confidence"),
                "pipeline": dict(pipeline_metadata),
            }
            if scene is None:
                scene = await Scene.create(
                    using_db=connection,
                    chapter_id=source.chapter_id,
                    sequence=sequence,
                    description=f"重制镜头 {sequence}",
                    prompt_params=item,
                    prompt=str(item.get("prompt", "")),
                    duration=float(item.get("duration_seconds", 0) or 0),
                    status=TaskStatusEnum.pending.value,
                    metadata=scene_metadata,
                )
            else:
                scene.description = f"重制镜头 {sequence}"
                scene.prompt_params = item
                scene.prompt = str(item.get("prompt", ""))
                scene.duration = float(item.get("duration_seconds", 0) or 0)
                scene.metadata = scene_metadata
                await scene.save(
                    using_db=connection,
                    update_fields=[
                        "description",
                        "prompt_params",
                        "prompt",
                        "duration",
                        "metadata",
                        "updated_at",
                    ],
                )
            await scene.assets.clear(using_db=connection)
            referenced = []
            for reference in item.get("asset_refs", []):
                if not isinstance(reference, dict):
                    continue
                asset = asset_index.get(str(reference.get("asset_id", "")))
                if asset is not None and asset not in referenced:
                    referenced.append(asset)
            if referenced:
                await scene.assets.add(*referenced, using_db=connection)

        owned_scenes = await Scene.filter(chapter_id=source.chapter_id).using_db(connection)
        for scene in owned_scenes:
            metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
            if (
                metadata.get("remake_source_id") == source.id
                and scene.sequence not in sequences
            ):
                await scene.delete(using_db=connection)
        return len(sequences)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return fallback
    return result if result > 0 else fallback


remake_result_persistence = RemakeResultPersistence()
