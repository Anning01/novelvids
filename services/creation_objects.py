"""Shared object lifecycle and ordering for page actions and agent transactions."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import re

from tortoise.expressions import F
from tortoise.query_utils import Prefetch
from tortoise.transactions import in_transaction

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


OBJECT_MODELS = {"asset": Asset, "variant": AssetVariant, "scene": Scene}
ACTIVE_TASK_STATUSES = [TaskStatusEnum.pending, TaskStatusEnum.queued, TaskStatusEnum.running]


@asynccontextmanager
async def project_write(novel_id: int):
    """Serialize dependent writes on PostgreSQL and acquire SQLite's write lock."""
    async with in_transaction() as connection:
        changed = await Novel.filter(id=novel_id).using_db(connection).update(updated_at=F("updated_at"))
        if not changed:
            raise ValueError("项目不存在")
        yield connection


class CreationObjects:
    def __init__(self, novel_id: int):
        self.novel_id = novel_id

    @staticmethod
    async def recovery_version(target) -> str:
        values = {name: getattr(target, name) for name in target._meta.db_fields
                  if name not in {'deleted_at', 'updated_at', 'sequence', 'metadata'}}
        values['metadata'] = {key: value for key, value in (target.metadata or {}).items() if key != '_removal'}
        if isinstance(target, Scene):
            # Include archived bindings too: restoring must not hide a removed
            # dependency or silently accept a historical relation being changed.
            values['asset_ids'] = await Asset.with_deleted().filter(scenes__id=target.id).order_by('id').values_list('id', flat=True)
        return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    async def get(self, kind: str, object_id: int, *, include_deleted: bool = False):
        model = OBJECT_MODELS.get(kind)
        if model is None:
            raise ValueError("不支持的创作对象")
        query = model.with_deleted() if include_deleted else model.all()
        scope = {"chapter__novel_id": self.novel_id} if kind == "scene" else (
            {"asset__novel_id": self.novel_id, "asset__deleted_at__isnull": True} if kind == "variant" else {"novel_id": self.novel_id})
        target = await query.filter(id=object_id, **scope).first()
        if target is None:
            raise ValueError("当前项目内不存在该对象，或对象已被移除")
        return target

    async def chapter(self, chapter_id: int) -> Chapter:
        chapter = await Chapter.get_or_none(id=chapter_id, novel_id=self.novel_id)
        if chapter is None:
            raise ValueError("章节不属于当前项目")
        return chapter

    async def active_assets(self, asset_ids: list[int]) -> list[Asset]:
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("不能重复绑定同一设定")
        assets = await Asset.filter(id__in=asset_ids, novel_id=self.novel_id)
        if len(assets) != len(asset_ids):
            raise ValueError("引用设定不存在、已移除或不属于当前项目")
        return assets

    async def create_setting(self, values: dict) -> Asset:
        if await Asset.with_deleted().filter(novel_id=self.novel_id, asset_type=values['asset_type'], canonical_name=values['canonical_name']).exists():
            raise ValueError('同名设定已存在；若已移除，请恢复原设定')
        return await Asset.create(novel_id=self.novel_id, **values)

    async def ensure_variant_chapters(self, asset_id: int, numbers: list[int], *, exclude_id: int | None = None):
        variants = await AssetVariant.filter(asset_id=asset_id)
        if any(variant.id != exclude_id and set(variant.chapter_numbers or []) & set(numbers) for variant in variants):
            raise ValueError('该角色在这些章节已有形态，请编辑已有形态或明确重新分配适用章节')

    async def create_variant(self, asset_id: int, values: dict) -> AssetVariant:
        await self.get('asset', asset_id)
        if await AssetVariant.with_deleted().filter(asset_id=asset_id, name=values['name']).exists():
            raise ValueError('同名形态已存在；若已移除，请恢复原形态')
        await self.ensure_variant_chapters(asset_id, values.get('chapter_numbers') or [])
        return await AssetVariant.create(asset_id=asset_id, **values)

    @staticmethod
    def rename_reference_values(fields: dict, old: str, new: str, *, variant: str | None = None) -> dict:
        # Asset renames include its qualified variant references. Variant renames
        # match the complete parent#variant token; prose and similar names stay intact.
        pattern = re.compile(r'@\{' + re.escape(old) + (r'(?=[#}])' if variant is None else r'\}'))
        replacement = '@{' + new + ('}' if variant is not None else '')
        def rewrite(value):
            if isinstance(value, str):
                return pattern.sub(lambda _: replacement, value)
            if isinstance(value, list):
                return [rewrite(item) for item in value]
            if isinstance(value, dict):
                return {key: rewrite(item) for key, item in value.items()}
            return value
        return {key: rewrite(value) for key, value in fields.items() if key in {'prompt', 'prompt_params', 'description'} and rewrite(value) != value}

    async def bind_assets(self, scene: Scene, asset_ids: list[int]) -> None:
        assets = await self.active_assets(asset_ids)
        await scene.assets.clear()
        if assets:
            await scene.assets.add(*assets)

    async def validate_variant_bindings(self, asset_ids: list[int], bindings: dict):
        if not isinstance(bindings, dict):
            raise ValueError('形态绑定格式无效')
        for raw_asset_id, raw_variant_id in bindings.items():
            try:
                asset_id, variant_id = int(raw_asset_id), int(raw_variant_id)
            except (ValueError, TypeError):
                raise ValueError('形态绑定标识无效') from None
            if asset_id not in asset_ids or not await AssetVariant.filter(
                id=variant_id, asset_id=asset_id, asset__novel_id=self.novel_id, asset__deleted_at__isnull=True).exists():
                raise ValueError('绑定形态不存在、已移除或不属于出镜设定')

    async def _ordered(self, chapter_id: int) -> list[Scene]:
        await self.chapter(chapter_id)
        return await Scene.filter(chapter_id=chapter_id).order_by("sequence", "id")

    @staticmethod
    async def _resequence(scenes: list[Scene]) -> None:
        changed = [(scene, index) for index, scene in enumerate(scenes, 1) if scene.sequence != index]
        # Negative IDs reserve distinct slots for both archived rows and moves.
        # All active public positions are positive and contiguous after the transaction.
        for scene, _ in changed:
            await Scene.filter(id=scene.id).update(sequence=-scene.id)
        for scene, index in changed:
            await Scene.filter(id=scene.id).update(sequence=index, updated_at=datetime.now(timezone.utc))
            scene.sequence = index

    @staticmethod
    def _insert_position(scenes: list[Scene], after_id: int | None) -> int:
        if after_id is None:
            return len(scenes)
        if after_id == 0:
            return 0
        for index, scene in enumerate(scenes):
            if scene.id == after_id:
                return index + 1
        raise ValueError("插入位置的分镜不在当前章节，或已被移除")

    async def create_scene(self, chapter_id: int, *, after_id: int | None, values: dict) -> Scene:
        scenes = await self._ordered(chapter_id)
        position = self._insert_position(scenes, after_id)
        # Use an unoccupied active position before shifting the complete order.
        scene = await Scene.create(chapter_id=chapter_id, sequence=max([s.sequence for s in scenes], default=0) + 1, **values)
        scenes.insert(position, scene)
        await self._resequence(scenes)
        await scene.refresh_from_db()
        return scene

    async def move_scene(self, scene: Scene, *, after_id: int | None) -> None:
        if after_id == scene.id:
            raise ValueError("不能把分镜移动到自身之后")
        scenes = [item for item in await self._ordered(scene.chapter_id) if item.id != scene.id]
        scenes.insert(self._insert_position(scenes, after_id), scene)
        await self._resequence(scenes)
        await scene.refresh_from_db()

    async def ensure_idle(self, kind: str, target) -> None:
        if kind == "scene" and await Video.filter(scene_id=target.id, status__in=ACTIVE_TASK_STATUSES).exists():
            raise ValueError("该分镜仍有生成任务，请先停止或等待完成")
        task_types = [AiTaskTypeEnum.reference_image, AiTaskTypeEnum.storyboard] if kind != "scene" else [AiTaskTypeEnum.video, AiTaskTypeEnum.storyboard]
        # Request JSON has different schemas across existing task types. Only
        # inspect active generation tasks and never copy credentials into errors.
        tasks = await AiTask.filter(status__in=ACTIVE_TASK_STATUSES, task_type__in=task_types).values('task_type', 'request_params')
        for task in tasks:
            params = task['request_params'] or {}
            if kind == 'scene':
                matches = params.get('scene_id') == target.id or (
                    task['task_type'] == AiTaskTypeEnum.storyboard and params.get('chapter_id') == target.chapter_id)
            else:
                matches = params.get('asset_id') == (target.asset_id if kind == 'variant' else target.id)
                if task['task_type'] == AiTaskTypeEnum.storyboard and params.get('novel_id') == self.novel_id:
                    matches = True
            if matches:
                raise ValueError("该对象仍有生成任务，请先停止或等待完成")

    async def variant_references(self, variant: AssetVariant) -> list[Scene]:
        scenes = await Scene.filter(assets__id=variant.asset_id, chapter__novel_id=self.novel_id).only(
            'id', 'chapter_id', 'sequence', 'description', 'metadata').prefetch_related(
                Prefetch('chapter', Chapter.all().only('id', 'number')))
        result = []
        for scene in scenes:
            selected = (scene.metadata or {}).get('asset_variant_ids') or {}
            explicit = selected.get(str(variant.asset_id), selected.get(variant.asset_id))
            if str(explicit) == str(variant.id) or (explicit is None and scene.chapter.number in (variant.chapter_numbers or [])):
                result.append(scene)
        return result

    async def archive(self, kind: str, object_id: int) -> dict:
        """Called under project_write. Retain rows, media and archived relations."""
        target = await self.get(kind, object_id)
        await self.ensure_idle(kind, target)
        snapshot: dict = {'content_version': await self.recovery_version(target)}
        if kind == 'asset':
            if await Scene.filter(assets__id=target.id).exists():
                raise ValueError("设定仍被分镜引用，请先明确并处理引用范围")
            variants = await AssetVariant.filter(asset_id=target.id)
            snapshot['variant_ids'] = [variant.id for variant in variants]
            snapshot['variant_versions'] = {str(variant.id): await self.recovery_version(variant) for variant in variants}
        elif kind == 'variant':
            if await self.variant_references(target):
                raise ValueError("该形态仍被分镜引用，请先调整对应分镜的形态绑定")
        else:
            snapshot['sequence'] = target.sequence
            ordered = await self._ordered(target.chapter_id)
            index = next(index for index, scene in enumerate(ordered) if scene.id == target.id)
            snapshot['after_id'] = ordered[index - 1].id if index else 0
        now = datetime.now(timezone.utc)
        snapshot['deleted_at'] = now.isoformat()
        values = {'deleted_at': now, 'updated_at': now}
        values['metadata'] = {**(target.metadata or {}), '_removal': snapshot}
        if kind == 'scene':
            values['sequence'] = -target.id
        await type(target).filter(id=target.id).update(**values)
        if kind == 'asset':
            await AssetVariant.filter(asset_id=target.id).update(deleted_at=now, updated_at=now)
        if kind == 'scene':
            await self._resequence(await self._ordered(target.chapter_id))
        return snapshot

    async def restore(self, kind: str, object_id: int, snapshot: dict | None = None):
        target = await self.get(kind, object_id, include_deleted=True)
        snapshot = snapshot or (target.metadata or {}).get('_removal')
        if not snapshot or 'deleted_at' not in snapshot:
            raise ValueError('对象没有可恢复的删除记录')
        if target.deleted_at is None:
            raise ValueError("对象已有后续恢复，不能覆盖")
        if target.deleted_at.astimezone(timezone.utc).isoformat() != snapshot['deleted_at']:
            raise ValueError("对象已有后续删除操作，不能覆盖")
        if snapshot.get('content_version') and await self.recovery_version(target) != snapshot['content_version']:
            raise ValueError('已移除对象的内容或引用已有后续修改，不能直接恢复覆盖')
        if kind == 'asset':
            variants = await AssetVariant.with_deleted().filter(id__in=snapshot['variant_ids'], asset_id=target.id)
            if len(variants) != len(snapshot['variant_ids']):
                raise ValueError('关联形态已有后续修改，不能直接恢复覆盖')
            for variant in variants:
                expected = (snapshot.get('variant_versions') or {}).get(str(variant.id))
                if variant.deleted_at != target.deleted_at or (expected and expected != await self.recovery_version(variant)):
                    raise ValueError('关联形态已有后续修改，不能直接恢复覆盖')
        if kind == 'variant':
            await self.ensure_variant_chapters(target.asset_id, target.chapter_numbers or [], exclude_id=target.id)
        if kind == 'scene':
            scenes = await self._ordered(target.chapter_id)
            position = self._insert_position(scenes, snapshot['after_id'])
            # Archived scene bindings must still resolve to active assets.
            rows = await target.assets.all()
            archived_ids = await Asset.with_deleted().filter(scenes__id=target.id, deleted_at__not_isnull=True).values_list('id', flat=True)
            if archived_ids:
                raise ValueError("分镜引用的设定已移除，请先恢复设定")
            await self.active_assets([asset.id for asset in rows])
            await self.validate_variant_bindings([asset.id for asset in rows], (target.metadata or {}).get('asset_variant_ids') or {})
        now = datetime.now(timezone.utc)
        metadata = {key: value for key, value in (target.metadata or {}).items() if key != '_removal'}
        await type(target).with_deleted().filter(id=target.id).update(deleted_at=None, updated_at=now, metadata=metadata)
        if kind == 'asset':
            await AssetVariant.with_deleted().filter(id__in=snapshot['variant_ids'], asset_id=target.id,
                deleted_at__in=[target.deleted_at, target.deleted_at.astimezone(timezone.utc)]).update(deleted_at=None, updated_at=now)
        if kind == 'scene':
            target.deleted_at = None
            scenes.insert(position, target)
            await self._resequence(scenes)
        await target.refresh_from_db()
        return target
