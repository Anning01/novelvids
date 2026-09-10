"""Execute validated creative operations inside one caller-owned transaction."""

from copy import deepcopy
import re

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.scene import Scene
from prompts.storyboard import format_storyboard_prompt, normalized_storyboard_reference_fields
from schemas.creation_agent import AgentTarget, StoryboardPromptEdit
from schemas.creation_objects import CreateScene, CreateSetting, CreateAssetSetting, CreateVariantSetting, DeleteObject, UpdateScene, UpdateSetting
from schemas.scene import SoraScenePromptConfig
from services.creation_agent.object_state import creation_version, object_label, object_state, object_version, write_fields
from services.creation_agent.prompt_edits import current_storyboard_structure, prepare_storyboard_edit, validate_image_prompt_edit, validate_prompt_dependencies
from services.creation_agent.tools import PromptEditService
from services.storyboard.strategies import storyboard_strategy_factory


class CreationOperations:
    def __init__(self, service):
        self.service = service
        self.objects = service.objects
        self.refs: dict[str, tuple[str, int]] = {}
        self.created: set[tuple[str, int]] = set()

    async def ref(self, value, kind: str):
        object_id = self.service.resolve(value, self.refs, kind)
        await self.service.checked(kind, object_id, self.created, write=False)
        return object_id

    async def chapters(self, chapter_ids: list[int] | None):
        ids = chapter_ids if chapter_ids is not None else [self.service.request.chapter_id]
        if not ids or None in ids or len(ids) != len(set(ids)):
            raise ValueError('请指定不重复的适用章节')
        result = []
        for chapter_id in ids:
            chapter = await self.service.scope.chapter(chapter_id)
            await self.service._check_creation_context(chapter.id)
            result.append(chapter)
        return result

    async def record(self, kind: str, target, operation: str, before: dict, recovery=None):
        after = await object_state(target)
        if operation == 'update':
            before, after = ({key: value for key, value in before.items() if after.get(key) != value},
                             {key: value for key, value in after.items() if before.get(key) != value})
        rules = await self.service.target_rules(AgentTarget(kind=kind, id=target.id)) if operation != 'delete' else self.service.rules.get((kind, target.id), [])
        version = await object_version(target)
        recovery = recovery or {}
        if operation == 'create':
            recovery['creation_version'] = await creation_version(target)
        item = {'kind': kind, 'target_id': target.id, 'target_label': await object_label(target),
                'operation': operation, 'before': before, 'after': {} if operation == 'delete' else after,
                'after_version': version, 'constraint_ids': [rule['id'] for rule in rules], 'recovery': recovery}
        if isinstance(target, AssetVariant):
            item['asset_id'] = target.asset_id
        if isinstance(target, Scene):
            item['chapter_id'] = target.chapter_id
        self.service.observed[(kind, target.id)] = version
        self.service.rules[(kind, target.id)] = deepcopy(rules)
        return item

    async def execute(self, operation) -> list[dict]:
        if isinstance(operation, CreateSetting):
            return [await self.create_setting(operation)]
        if isinstance(operation, CreateScene):
            return [await self.create_scene(operation)]
        if isinstance(operation, UpdateSetting):
            return await self.update_setting(operation)
        if isinstance(operation, UpdateScene):
            return [await self.update_scene(operation)]
        if isinstance(operation, DeleteObject):
            target = await self.service.checked(operation.target.kind, operation.target.id, self.created)
            before = await object_state(target)
            label = await object_label(target)
            order = await self.service._order(target.chapter_id) if isinstance(target, Scene) else None
            recovery = await self.objects.archive(operation.target.kind, target.id)
            if order is not None:
                recovery.update(order_before=order, order_after=await self.service._order(target.chapter_id))
            item = await self.record(operation.target.kind, target, 'delete', before, recovery)
            item['target_label'] = label
            return [item]
        raise ValueError('不支持的创作操作')

    async def create_setting(self, operation: CreateSetting):
        chapters = await self.chapters(operation.chapter_ids)
        parent_id = await self.ref(operation.parent, 'asset') if isinstance(operation, CreateVariantSetting) else None
        await self.service.scope.creation(kind=operation.kind, chapter_ids=[c.id for c in chapters], parent_id=parent_id)
        if isinstance(operation, CreateAssetSetting) and operation.is_global and self.service.request.write_scope != 'project':
            raise ValueError('全书共用设定需要项目操作范围')
        validate_image_prompt_edit(operation.prompt, '')
        if isinstance(operation, CreateAssetSetting):
            target = await self.objects.create_setting({
                'canonical_name': operation.name, 'asset_type': operation.asset_type, 'aliases': operation.aliases,
                'description': operation.description, 'base_traits': operation.prompt, 'is_global': operation.is_global,
                'source_chapters': [c.number for c in chapters], 'last_updated_chapter': max(c.number for c in chapters)})
        else:
            target = await self.objects.create_variant(parent_id, {
                'name': operation.name, 'description': operation.description, 'base_traits': operation.prompt,
                'chapter_numbers': [c.number for c in chapters]})
        self.refs[operation.client_ref] = (operation.kind, target.id)
        self.created.add((operation.kind, target.id))
        return await self.record(operation.kind, target, 'create', {})

    async def bindings(self, scene: Scene, assets, variant_refs):
        asset_ids = [await self.ref(value, 'asset') for value in assets] if assets is not None else (
            await scene.assets.all().values_list('id', flat=True))
        await self.objects.active_assets(asset_ids)
        bindings = {str(key): value for key, value in ((scene.metadata or {}).get('asset_variant_ids') or {}).items()
                    if int(key) in asset_ids}
        if variant_refs is not None:
            bindings = {}
            for value in variant_refs:
                variant_id = await self.ref(value, 'variant')
                variant = await self.objects.get('variant', variant_id)
                if variant.asset_id not in asset_ids or str(variant.asset_id) in bindings:
                    raise ValueError('形态必须属于出镜设定，且同一设定只能选择一个形态')
                bindings[str(variant.asset_id)] = variant.id
        return {'asset_ids': asset_ids, 'variant_bindings': bindings}

    async def scene_prompt(self, scene: Scene, *, prompt=None, structure=None, visual=None, previous=None):
        entities = await PromptEditService._entities(scene)
        strategy = storyboard_strategy_factory.resolve(scene.chapter.novel.storyboard_strategy)
        if structure is not None:
            candidate = SoraScenePromptConfig.model_validate({**structure.model_dump(), 'sequence': scene.sequence,
                **(visual.model_dump(exclude_unset=True) if visual else {}),
                'duration': f'{scene.duration:g}s', 'description': scene.description})
        elif visual is not None or previous is not None:
            old = previous or scene
            candidate = current_storyboard_structure(prompt=old.prompt, params=old.prompt_params or {}, sequence=old.sequence,
                description=old.description, duration=old.duration, entities=entities, strategy=strategy)
            if candidate:
                candidate = SoraScenePromptConfig.model_validate({**candidate.model_dump(),
                    **(visual.model_dump(exclude_unset=True) if visual else {}),
                    'sequence': scene.sequence, 'duration': f'{scene.duration:g}s', 'description': scene.description})
            elif visual is not None:
                raise ValueError('当前为手工文本或引用已变化，请提交完整 prompt 保留当前画面')
        else:
            candidate = None
        if prompt is not None:
            # The shared legacy path preserves tracks and expands actual references.
            values = prepare_storyboard_edit(edit=StoryboardPromptEdit(scene_id=scene.id, legacy_prompt=prompt),
                prompt=scene.prompt, params=scene.prompt_params or {}, sequence=scene.sequence,
                description=scene.description, duration=scene.duration, entities=entities, strategy=strategy)
            self.validate_timing(values['prompt'], scene.duration)
        elif candidate:
            candidate = SoraScenePromptConfig.model_validate({**candidate.model_dump(), **normalized_storyboard_reference_fields(candidate, entities)})
            for key, value in candidate.model_dump(exclude={'dialogue', 'narration'}).items():
                if key not in {'sequence', 'duration'}:
                    validate_prompt_dependencies(str(value), entities)
            values = {'prompt': format_storyboard_prompt(candidate, entities=entities, strategy=strategy),
                      'prompt_params': candidate.model_dump(exclude={'sequence', 'description', 'duration'})}
            self.validate_timing(values['prompt'], scene.duration)
        else:
            values = prepare_storyboard_edit(edit=StoryboardPromptEdit(scene_id=scene.id, legacy_prompt=scene.prompt or ''),
                prompt=scene.prompt, params=scene.prompt_params or {}, sequence=scene.sequence,
                description=scene.description, duration=scene.duration, entities=entities, strategy=strategy)
            self.validate_timing(values['prompt'], scene.duration)
        await write_fields(self.objects, scene, values)

    @staticmethod
    def validate_timing(prompt: str, duration: float):
        intervals = re.findall(r'(\d+(?:\.\d+)?)\s*s?\s*[-–~]\s*(\d+(?:\.\d+)?)\s*s', prompt)
        if any(float(start) < 0 or float(end) <= float(start) or float(end) > duration + .001 for start, end in intervals):
            raise ValueError('提示词中的动作时间轴超出分镜时长，请同步调整时间轴')

    async def create_scene(self, operation: CreateScene):
        chapter = await self.service.scope.chapter(operation.chapter_id)
        await self.service._check_creation_context(chapter.id)
        after = await self.ref(operation.after, 'scene') if operation.after else operation.after
        await self.service.scope.creation(kind='scene', chapter_ids=[chapter.id], anchor_id=after)
        before_order = await self.service._order(chapter.id)
        target = await self.objects.create_scene(chapter.id, after_id=after, values={
            'description': operation.description, 'duration': operation.duration, 'prompt': ''})
        await write_fields(self.objects, target, await self.bindings(target, operation.assets, operation.variant_refs))
        await self.scene_prompt(target, prompt=operation.prompt, structure=operation.structure)
        self.refs[operation.client_ref] = ('scene', target.id)
        self.created.add(('scene', target.id))
        return await self.record('scene', target, 'create', {}, {
            'order_before': before_order, 'order_after': await self.service._order(chapter.id)})

    async def update_scene(self, operation: UpdateScene):
        target = await self.service.checked('scene', operation.scene_id, self.created)
        await self.objects.ensure_idle('scene', target)
        before = await object_state(target)
        previous = deepcopy(target)
        old_entities = await PromptEditService._entities(previous)
        old_strategy = storyboard_strategy_factory.resolve(previous.chapter.novel.storyboard_strategy)
        old_structure = current_storyboard_structure(prompt=previous.prompt, params=previous.prompt_params or {},
            sequence=previous.sequence, description=previous.description, duration=previous.duration,
            entities=old_entities, strategy=old_strategy)
        fields = operation.fields
        updates = fields.model_dump(exclude_unset=True, include={'description', 'duration'})
        if fields.assets is not None or fields.variant_refs is not None:
            await self.service._check_creation_context(target.chapter_id)
            updates.update(await self.bindings(target, fields.assets, fields.variant_refs))
            if old_structure is None and fields.prompt is None:
                raise ValueError('当前是历史手工提示词；改变出镜关系时请同时提交完整 prompt，移除旧引用并保留当前画面和声音')
        await write_fields(self.objects, target, updates)
        if fields.model_fields_set - {'after'}:
            await self.scene_prompt(target, prompt=fields.prompt, structure=old_structure, visual=fields.visual, previous=previous)
        recovery = {}
        if 'after' in fields.model_fields_set:
            after = await self.ref(fields.after, 'scene') if fields.after else fields.after
            recovery['order_before'] = await self.service._order(target.chapter_id)
            await self.objects.move_scene(target, after_id=after)
            recovery['order_after'] = await self.service._order(target.chapter_id)
        return await self.record('scene', target, 'update', before, recovery)

    async def update_setting(self, operation: UpdateSetting):
        kind = operation.target.kind
        target = await self.service.checked(kind, operation.target.id, self.created)
        await self.objects.ensure_idle(kind, target)
        before = await object_state(target)
        fields = operation.fields
        updates = fields.model_dump(exclude_unset=True, include={'description', 'aliases', 'is_global'})
        if fields.is_global is not None and self.service.request.write_scope != 'project':
            raise ValueError('改变全书共用关系需要项目操作范围')
        if fields.prompt is not None:
            validate_image_prompt_edit(fields.prompt, target.base_traits or '')
            updates['base_traits'] = fields.prompt
        if fields.name is not None:
            updates['canonical_name' if kind == 'asset' else 'name'] = fields.name
        if fields.chapter_ids is not None:
            chapters = await self.chapters(fields.chapter_ids)
            numbers = [c.number for c in chapters]
            if kind == 'asset':
                used = await Scene.filter(assets__id=target.id).prefetch_related('chapter')
                if any(scene.chapter.number not in numbers for scene in used):
                    raise ValueError('移出章节前请先处理仍引用该设定的分镜')
                updates.update(source_chapters=numbers, last_updated_chapter=max(numbers))
            else:
                used = await self.objects.variant_references(target)
                if any(scene.chapter.number not in numbers for scene in used):
                    raise ValueError('形态仍被未包含的章节引用，不能直接移除适用关系')
                await self.objects.ensure_variant_chapters(target.asset_id, numbers, exclude_id=target.id)
                updates['chapter_numbers'] = numbers
        # Keep canonical references resolvable during a rename; actual text
        # replacements are precise @{...} tokens, never arbitrary substrings.
        reference_changes = []
        if kind == 'asset' and fields.name is not None and fields.name != target.canonical_name:
            reference_changes = await self.rename_references(target, fields.name)
            updates['aliases'] = list(dict.fromkeys([*(fields.aliases if fields.aliases is not None else target.aliases or []), target.canonical_name]))
        elif kind == 'variant' and fields.name is not None and fields.name != target.name:
            reference_changes = await self.rename_references(target, fields.name)
        await write_fields(self.objects, target, updates)
        return [await self.record(kind, target, 'update', before), *reference_changes]

    async def rename_references(self, target: Asset | AssetVariant, new_name: str):
        changes = []
        asset = target if isinstance(target, Asset) else await self.objects.get('asset', target.asset_id)
        old_name = asset.canonical_name if isinstance(target, Asset) else f'{asset.canonical_name}#{target.name}'
        new_name = new_name if isinstance(target, Asset) else f'{asset.canonical_name}#{new_name}'
        for scene in await Scene.filter(assets__id=asset.id):
            # Reference replacement is a derived consequence of the explicitly
            # selected setting rename. All other scene fields remain untouched.
            before = await object_state(scene)
            updates = self.objects.rename_reference_values(before, old_name, new_name,
                variant=target.name if isinstance(target, AssetVariant) else None)
            if not updates:
                continue
            await self.service.checked('scene', scene.id, self.created, write=False)
            await self.objects.ensure_idle('scene', scene)
            await write_fields(self.objects, scene, updates)
            changes.append(await self.record('scene', scene, 'update', before))
        return changes
