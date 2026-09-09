"""Two scoped prompt writers with transactional history and optimistic concurrency."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID
from collections.abc import Callable, Awaitable

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import PromptChange
from models.scene import Scene
from models.novel import Novel
from schemas.creation_agent import ImagePromptEdit, StoryboardPromptEdit
from schemas.scene import SceneEntity
from services.creation_agent.prompt_edits import prepare_storyboard_edit, validate_image_prompt_edit, current_storyboard_structure
from services.storyboard.strategies import storyboard_strategy_factory
from services.storyboard.entities import visual_entity_description
from utils.enums import TaskStatusEnum, AssetTypeEnum


class PromptEditConflict(ValueError):
    """The caller must re-read state instead of overwriting newer content."""


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def prompt_version(target: Asset | AssetVariant | Scene) -> str:
    fields = ("prompt", "prompt_params") if isinstance(target, Scene) else ("base_traits",)
    return _digest({"id": target.id, "updated_at": target.updated_at.astimezone(timezone.utc).isoformat(),
                    **{field: getattr(target, field) for field in fields}})


class PromptEditService:
    """Scope is fixed by the authenticated request, never by tool arguments."""

    def __init__(self, *, novel_id: int, task_id: UUID,
                 allowed_targets: set[tuple[str, int]], max_batch_size: int,
                 authorization_check: Callable[[], Awaitable[None]] | None = None,
                 context_check: Callable[[], Awaitable[list[dict] | None]] | None = None):
        if max_batch_size < 1:
            raise ValueError("批次上限必须大于0")
        self.novel_id = novel_id
        self.task_id = task_id
        self.allowed_targets = frozenset(allowed_targets)
        self.max_batch_size = max_batch_size
        self.authorization_check = authorization_check
        self.context_check = context_check

    async def _target(self, kind: str, target_id: int, connection):
        if self.authorization_check:
            await self.authorization_check()
        if (kind, target_id) not in self.allowed_targets:
            raise ValueError("目标不在当前请求授权范围内")
        if kind == "scene":
            query = Scene.filter(id=target_id, chapter__novel_id=self.novel_id)
        elif kind == "asset":
            query = Asset.filter(id=target_id, novel_id=self.novel_id)
        elif kind == "variant":
            query = AssetVariant.filter(id=target_id, asset__novel_id=self.novel_id)
        else:
            raise ValueError("不支持的 Prompt 目标")
        target = await query.using_db(connection).first()
        if target is None:
            raise ValueError("当前项目内不存在该目标")
        return target

    async def _entities(self, scene: Scene) -> list[SceneEntity]:
        from services.video.asset_resolver import normalize_selected_variant_ids, select_asset_variant

        await scene.fetch_related("chapter__novel", "assets__variants")
        selected = normalize_selected_variant_ids((scene.metadata or {}).get("asset_variant_ids"))
        entities = []
        for asset in scene.assets:
            variant = select_asset_variant(asset, scene.chapter.number, selected)
            explicit_id = selected.get(asset.id)
            if explicit_id is not None and variant is None:
                raise ValueError("已选择的资产形态不存在，请先修复素材绑定")
            source = variant or asset
            name = asset.canonical_name
            aliases = list(asset.aliases or [])
            if variant:
                aliases.append(f"{name}#{variant.name}")
            entities.append(SceneEntity(
                asset_id=asset.id, name=name, aliases=aliases,
                description=visual_entity_description(source.description, source.base_traits),
                asset_type=AssetTypeEnum(asset.asset_type).nickname,
            ))
        return entities

    async def _replay(self, tool_call_id: str, request_hash: str):
        change = await PromptChange.get_or_none(task_id=self.task_id, tool_call_id=tool_call_id, novel_id=self.novel_id)
        if change and change.request_hash != request_hash:
            raise PromptEditConflict("同一工具调用标识不能对应不同的修改请求")
        return change

    async def read_targets(self, *, for_model: bool = False) -> list[dict]:
        """Return current versions only for the request's frozen target set."""
        targets = []
        async with in_transaction() as connection:
            for kind, target_id in sorted(self.allowed_targets):
                target = await self._target(kind, target_id, connection)
                data = {"kind": kind, "id": target_id, "version": prompt_version(target)}
                if isinstance(target, Scene):
                    entities = await self._entities(target)
                    data.update(prompt=target.prompt, prompt_params=target.prompt_params,
                                sequence=target.sequence, duration=target.duration,
                                description=target.description,
                                entities=[entity.model_dump() for entity in entities])
                    if for_model:
                        structure = current_storyboard_structure(prompt=target.prompt, params=target.prompt_params or {},
                            sequence=target.sequence, description=target.description, duration=target.duration,
                            entities=entities, strategy=storyboard_strategy_factory.resolve(target.chapter.novel.storyboard_strategy))
                        data['edit_mode'] = 'changes' if structure else 'legacy_prompt'
                        if structure:
                            # The rendered prompt duplicates these complete parameters
                            # and entity definitions; retain its version for safe writes.
                            data.pop('prompt')
                else:
                    data.update(prompt=target.base_traits, description=target.description,
                                name=target.canonical_name if isinstance(target, Asset) else target.name)
                    if isinstance(target, AssetVariant):
                        await target.fetch_related("asset")
                        data["base_asset"] = {"id": target.asset.id, "name": target.asset.canonical_name,
                                              "prompt": target.asset.base_traits, "description": target.asset.description}
                targets.append(data)
        return targets

    async def _apply(self, edits: list[ImagePromptEdit] | list[StoryboardPromptEdit], *, tool_call_id: str):
        if not tool_call_id or len(tool_call_id) > 200:
            raise ValueError("工具调用标识无效")
        if not 1 <= len(edits) <= self.max_batch_size:
            raise ValueError("修改目标数量超出当前批次上限")
        request_hash = _digest([edit.model_dump(mode="json") for edit in edits])
        try:
            async with in_transaction() as connection:
                replay = await self._replay(tool_call_id, request_hash)
                if replay:
                    return replay
                task = await AiTask.filter(id=self.task_id).using_db(connection).select_for_update().first()
                if task is None or (task.request_params or {}).get("novel_id") != self.novel_id:
                    raise ValueError("运行不属于当前项目")
                if task.status != TaskStatusEnum.running.value:
                    raise PromptEditConflict("运行已停止或结束，不能继续写入")
                # The conditional write also acquires SQLite's write lock before targets change.
                active = await AiTask.filter(id=task.id, status=TaskStatusEnum.running.value).using_db(connection).update(status=TaskStatusEnum.running.value)
                if not active:
                    raise PromptEditConflict("运行已停止，不能继续写入")
                await Novel.filter(id=self.novel_id).using_db(connection).select_for_update().first()
                constraints = (await self.context_check() if self.context_check else None) or []
                seen = set()
                changes = []
                for edit in edits:
                    kind = "scene" if isinstance(edit, StoryboardPromptEdit) else edit.target_kind
                    target_id = edit.scene_id if isinstance(edit, StoryboardPromptEdit) else edit.target_id
                    if (kind, target_id) in seen:
                        raise ValueError("同一批次不能重复修改同一目标")
                    seen.add((kind, target_id))
                    if not edit.expected_version:
                        raise ValueError("写入请求缺少服务端并发版本")
                    target = await self._target(kind, target_id, connection)
                    if prompt_version(target) != edit.expected_version:
                        raise PromptEditConflict("目标已被修改，请重新读取最新 Prompt")
                    if isinstance(edit, StoryboardPromptEdit):
                        entities = await self._entities(target)
                        values = prepare_storyboard_edit(
                            edit=edit, prompt=target.prompt,
                            params=target.prompt_params or {}, sequence=target.sequence,
                            description=target.description, duration=target.duration,
                            entities=entities,
                            strategy=storyboard_strategy_factory.resolve(target.chapter.novel.storyboard_strategy),
                        )
                    else:
                        validate_image_prompt_edit(edit.prompt, target.base_traits or "")
                        values = {"base_traits": edit.prompt}
                    before = {field: getattr(target, field) for field in values}
                    version = await self._write(target, values, connection)
                    if isinstance(target, Scene):
                        label = f"第 {target.chapter.number} 章 · 分镜 {target.sequence}"
                    elif isinstance(target, AssetVariant):
                        parent = await Asset.get(id=target.asset_id).using_db(connection)
                        label = f"{parent.canonical_name} · {target.name}"
                    else:
                        label = target.canonical_name
                    changes.append({"kind": kind, "target_id": target_id,
                                    "target_label": label,
                                    **({"asset_id": target.asset_id} if isinstance(target, AssetVariant) else {}),
                                    "constraint_ids": [rule['id'] for rule in constraints
                                                       if {"kind": kind, "id": target_id} in rule['applies_to']],
                                    "before": before, "after": values, "after_version": version})
                return await PromptChange.create(
                    novel_id=self.novel_id, task_id=self.task_id,
                    tool_call_id=tool_call_id, request_hash=request_hash, changes=changes,
                    using_db=connection,
                )
        except IntegrityError:
            replay = await self._replay(tool_call_id, request_hash)
            if replay:
                return replay
            raise

    @staticmethod
    async def _write(target, values: dict, connection) -> str:
        now = datetime.now(timezone.utc)
        # SQLite retains offsets in timestamp text; legacy rows can use local time or UTC.
        updated = await type(target).filter(
            id=target.id,
            updated_at__in=[target.updated_at, target.updated_at.astimezone(timezone.utc)],
        ).using_db(connection).update(**values, updated_at=now)
        if not updated:
            raise PromptEditConflict("目标已被修改，请重新读取最新 Prompt")
        await target.refresh_from_db(using_db=connection)
        return prompt_version(target)

    async def update_image_prompt(self, edits: list[ImagePromptEdit], *, tool_call_id: str):
        return await self._apply(edits, tool_call_id=tool_call_id)

    async def update_storyboard_prompt(self, edits: list[StoryboardPromptEdit], *, tool_call_id: str):
        return await self._apply(edits, tool_call_id=tool_call_id)

    async def undo(self, change_id: int):
        async with in_transaction() as connection:
            change = await PromptChange.filter(id=change_id, novel_id=self.novel_id, task_id=self.task_id).using_db(connection).select_for_update().first()
            if change is None:
                raise ValueError("当前运行中不存在该修改记录")
            if change.reverted_at:
                return change
            for item in change.changes:
                target = await self._target(item["kind"], item["target_id"], connection)
                # Only these prompt fields are reverted. A later video setting
                # changes updated_at too, but must not invalidate an unchanged prompt.
                if any(getattr(target, field) != value for field, value in item['after'].items()):
                    raise PromptEditConflict("该目标已有后续修改，不能直接撤销覆盖")
                await self._write(target, item["before"], connection)
            change.reverted_at = datetime.now(timezone.utc)
            await change.save(using_db=connection, update_fields=["reverted_at", "updated_at"])
            return change
