"""Atomic creative change sets, scoped discovery and conflict-aware undo."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timezone

from tortoise.exceptions import IntegrityError

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import AgentMessage, PromptChange
from models.scene import Scene
from schemas.creation_agent import AgentRunRequest, AgentTarget, PromptStatusRequest
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.catalog import CreationCatalog
from services.creation_agent.memory import creation_memory
from services.creation_agent.object_state import creation_version, object_label, object_state, object_version, write_fields
from services.creation_agent.scope import CreationWriteScope
from services.creation_agent.tools import PromptEditConflict, PromptEditService, _digest
from services.creation_objects import CreationObjects, project_write
from utils.enums import TaskStatusEnum


class CreationChanges:
    def __init__(self, *, novel_id: int, task_id, request: AgentRunRequest, max_batch_size: int,
                 authorization_check: Callable[[], Awaitable[None]] | None = None,
                 max_context_characters: int = 32000):
        self.novel_id = novel_id
        self.task_id = task_id
        self.request = request.model_copy(deep=True)
        self.max_batch_size = max_batch_size
        self.authorization_check = authorization_check
        self.chapter_character_budget = max(500, max_context_characters // 3)
        self.scope = CreationWriteScope(novel_id, request)
        self.objects = CreationObjects(novel_id)
        self.catalog = CreationCatalog(novel_id, request.chapter_id)
        self.observed: dict[tuple[str, int], str] = {}
        self.rules: dict[tuple[str, int], list[dict]] = {}
        self.creation_rules: dict[int, list[dict]] = {}

    async def authorize(self):
        if self.authorization_check:
            await self.authorization_check()

    async def recent_changes(self, source: AgentMessage | None, page: int) -> dict:
        """Durable receipts survive model-history compression; never echo prompts."""
        await self.authorize()
        if source is None:
            return {'items': [], 'total': 0, 'next_page': None}
        page_size = 8
        query = PromptChange.filter(novel_id=self.novel_id,
            task__agent_messages__conversation_id=source.conversation_id,
            task__agent_messages__role='user').distinct()
        total = await query.count()
        rows = await query.order_by('-id').offset((page - 1) * page_size).limit(page_size)
        return {'items': [{'change_id': row.id, 'status': 'reverted' if row.reverted_at else 'saved',
            'changes': [{'operation': item.get('operation', 'update'), 'kind': item['kind'],
                         'name': item.get('target_label', ''), 'chapter_id': item.get('chapter_id')}
                        for item in row.changes]} for row in rows],
            'total': total, 'next_page': page + 1 if page * page_size < total else None}

    async def target_rules(self, target: AgentTarget) -> list[dict]:
        return await creation_memory.applicable(self.novel_id, PromptStatusRequest(
            chapter_id=self.request.chapter_id, targets=[target]))

    async def creative_target(self, kind: str, object_id: int):
        target = await self.objects.get(kind, object_id)
        asset = target if isinstance(target, Asset) else await self.objects.get('asset', target.asset_id) if isinstance(target, AssetVariant) else None
        if asset is not None and asset.asset_type not in {1, 2, 3}:
            raise ValueError('助手仅管理人物、场景、道具及其形态')
        return target

    async def read_creation_context(self, chapter_id: int) -> dict:
        await self.authorize()
        chapter = await self.objects.chapter(chapter_id)
        # Include prospective chapter and asset-scoped rules, with their scope
        # intact. New targets have no IDs yet; never inherit old target-only rules.
        assets = await Asset.filter(novel_id=self.novel_id, asset_type__in=[1, 2, 3])
        rules = await creation_memory.for_generation(chapter, assets)
        self.creation_rules[chapter.id] = deepcopy(rules)
        return {'chapter_id': chapter.id, 'constraints_for_new_objects': rules}

    async def read(self, targets: list[AgentTarget]) -> list[dict]:
        await self.authorize()
        if not 1 <= len(targets) <= self.max_batch_size:
            raise ValueError('读取对象数量超出本轮上限')
        # Content, references and the observed version must be one snapshot.
        # Otherwise a page write between two reads could authorize stale content
        # against a newer version. The lock is released before any model call.
        async with project_write(self.novel_id):
            return await self._read_locked(targets)

    async def _read_locked(self, targets: list[AgentTarget]) -> list[dict]:
        result = []
        for ref in targets:
            await self.creative_target(ref.kind, ref.id)
        # Reuse the existing standalone prompt/entity projections.
        reader = PromptEditService(novel_id=self.novel_id, task_id=self.task_id,
            allowed_targets={(t.kind, t.id) for t in targets}, max_batch_size=self.max_batch_size)
        prompt_data = {(item['kind'], item['id']): item for item in await reader.read_targets(for_model=True)}
        for ref in targets:
            target = await self.objects.get(ref.kind, ref.id)
            key = (ref.kind, ref.id)
            self.observed[key] = await object_version(target)
            rules = await self.target_rules(ref)
            self.rules[key] = deepcopy(rules)
            data = prompt_data[key]
            data.pop('version', None)
            data.update(name=await object_label(target), constraints=rules,
                        fields=await object_state(target), references=await self.catalog.references(ref.kind, ref.id))
            # The prompt projection already contains canonical structured fields.
            data['fields'].pop('prompt', None)
            data['fields'].pop('prompt_params', None)
            data['fields'].pop('base_traits', None)
            if isinstance(target, Scene):
                data['chapter_id'] = target.chapter_id
            result.append(data)
        return result

    async def checked(self, kind: str, object_id: int, created: set[tuple[str, int]], *, write=True):
        target = await self.creative_target(kind, object_id)
        key = (kind, object_id)
        if write:
            await self.scope.target(kind, target, new=key in created)
        if key not in created:
            if key not in self.observed:
                raise ValueError(f'写入或引用前请先读取对象详情，不能使用未经读取的 ID：{kind} {object_id}（{await object_label(target)}）')
            if self.observed[key] != await object_version(target):
                raise PromptEditConflict('对象已有变化，请重新读取后重试')
            if self.rules[key] != await self.target_rules(AgentTarget(kind=kind, id=object_id)):
                raise PromptEditConflict('适用约束已有变化，请重新读取后重试')
        return target

    async def _check_creation_context(self, chapter_id: int):
        chapter = await self.objects.chapter(chapter_id)
        assets = await Asset.filter(novel_id=self.novel_id, asset_type__in=[1, 2, 3])
        current = await creation_memory.for_generation(chapter, assets)
        if self.creation_rules.get(chapter_id) != current:
            raise ValueError('新增或调整关系前请读取当前章节创作上下文和适用约束')

    @staticmethod
    def resolve(value, refs: dict[str, tuple[str, int]], kind: str):
        if isinstance(value, str):
            result = refs.get(value)
            if result is None or result[0] != kind:
                raise ValueError('临时引用不存在或类型不匹配；只能引用同批次已创建对象')
            return result[1]
        return value

    async def _order(self, chapter_id: int):
        return await Scene.filter(chapter_id=chapter_id).order_by('sequence', 'id').values_list('id', flat=True)

    async def require_running(self):
        task = await AiTask.get_or_none(id=self.task_id)
        if task is None or (task.request_params or {}).get('novel_id') != self.novel_id:
            raise ValueError('运行不属于当前项目')
        locked = await AiTask.filter(id=task.id, status=TaskStatusEnum.running).update(status=TaskStatusEnum.running)
        if not locked:
            raise ValueError('运行已停止或结束，不能继续写入')

    async def apply(self, change_set: CreationChangeSet, *, tool_call_id: str):
        from services.creation_agent.operations import CreationOperations

        if not tool_call_id or len(tool_call_id) > 200:
            raise ValueError('工具调用标识无效')
        if not 1 <= len(change_set.operations) <= self.max_batch_size:
            raise ValueError('本批次对象数量超过配置上限')
        digest = _digest(change_set.model_dump(mode='json'))
        # Internal snapshots change only after the DB transaction commits.
        observed_before, rules_before = dict(self.observed), deepcopy(self.rules)
        try:
            async with project_write(self.novel_id):
                await self.authorize()
                self.scope.writable()
                replay = await PromptChange.get_or_none(task_id=self.task_id, tool_call_id=tool_call_id, novel_id=self.novel_id)
                if replay:
                    if replay.request_hash != digest:
                        raise PromptEditConflict('同一调用标识不能对应不同操作')
                    return replay
                await self.require_running()
                executor = CreationOperations(self)
                changes = []
                for operation in change_set.operations:
                    changes.extend(await executor.execute(operation))
                    if len(changes) > self.max_batch_size:
                        raise ValueError('关联对象变化超过本批次上限，请缩小范围或分批处理')
                result = await PromptChange.create(novel_id=self.novel_id, task_id=self.task_id,
                    tool_call_id=tool_call_id, request_hash=digest, changes=changes)
            return result
        except IntegrityError:
            self.observed, self.rules = observed_before, rules_before
            raise ValueError('对象名称或位置已存在，可能位于已移除记录中；请查询或恢复原对象') from None
        except Exception:
            self.observed, self.rules = observed_before, rules_before
            raise

    async def undo_for_run(self, change_id: int, source: AgentMessage | None):
        """Conversational undo is a write by the current, frozen run scope."""
        async with project_write(self.novel_id):
            await self.authorize()
            self.scope.writable()
            await self.require_running()
            change = await PromptChange.get_or_none(id=change_id, novel_id=self.novel_id)
            if change is None or source is None or not await AgentMessage.filter(
                task_id=change.task_id, conversation_id=source.conversation_id).exists():
                raise ValueError('本会话不存在该操作记录')
            if change.reverted_at:
                return change
            for item in change.changes:
                target = await self.objects.get(item['kind'], item['target_id'], include_deleted=item.get('operation') == 'delete')
                await self.scope.target(item['kind'], target)
            previous = await AgentMessage.get(task_id=change.task_id, role='user')
            original = AgentRunRequest.model_validate(previous.run_input)
            owner = CreationChanges(novel_id=self.novel_id, task_id=change.task_id, request=original,
                max_batch_size=self.max_batch_size, authorization_check=self.authorization_check)
            return await owner.undo(change_id)

    async def undo(self, change_id: int):
        try:
            return await self._undo_locked(change_id)
        except IntegrityError:
            raise PromptEditConflict('原名称或位置已被其他对象使用，不能撤销覆盖；请先处理冲突') from None

    async def _undo_locked(self, change_id: int):
        async with project_write(self.novel_id):
            await self.authorize()
            change = await PromptChange.get_or_none(id=change_id, novel_id=self.novel_id, task_id=self.task_id)
            if change is None:
                raise ValueError('当前运行不存在该操作记录')
            if change.reverted_at:
                return change
            for item in reversed(change.changes):
                kind, object_id = item['kind'], item['target_id']
                operation = item.get('operation', 'update')
                target = await self.objects.get(kind, object_id, include_deleted=operation == 'delete')
                await self.objects.ensure_idle(kind, target)
                recovery = item.get('recovery') or {}
                if 'order_after' in recovery and await self._order(target.chapter_id) != recovery['order_after']:
                    raise PromptEditConflict('本章分镜顺序已有后续修改，不能直接撤销覆盖')
                if operation == 'delete':
                    target = await self.objects.restore(kind, object_id, recovery)
                else:
                    current = await object_state(target)
                    if any(current.get(key) != value for key, value in item['after'].items()):
                        raise PromptEditConflict('该对象已有后续修改，不能直接撤销覆盖')
                    if operation == 'create':
                        if await creation_version(target) != recovery.get('creation_version'):
                            raise PromptEditConflict('新增对象已有后续修改，请先处理后续操作')
                        await self.objects.archive(kind, object_id)
                    else:
                        await write_fields(self.objects, target, item['before'])
                if 'order_before' in recovery:
                    scenes = {scene.id: scene for scene in await Scene.filter(chapter_id=target.chapter_id)}
                    if set(scenes) != set(recovery['order_before']):
                        raise PromptEditConflict('本章分镜集合已有变化，不能恢复原顺序')
                    await self.objects._resequence([scenes[object_id] for object_id in recovery['order_before']])
            change.reverted_at = datetime.now(timezone.utc)
            await change.save(update_fields=['reverted_at', 'updated_at'])
            return change
