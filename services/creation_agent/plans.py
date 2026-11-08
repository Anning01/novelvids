"""Server-owned plans, bounded discovery and immutable confirmation snapshots."""

from uuid import UUID, uuid5

from fastapi import HTTPException

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentMessage
from models.scene import Scene
from schemas.creation_agent import AgentRunRequest
from schemas.creation_plan import CreationBrief, CreationPlan, CreationPlanDraft
from services.creation_agent.object_state import object_version
from services.creation_agent.plan_sources import CreationSourceLoader, chapter_version, fingerprint, plan_activity
from utils.messages import localized_message

PLAN_KEY = 'creation:plan'


async def load_plan(task_id, *, novel_id=None):
    row = await AgentOperation.get_or_none(task_id=task_id, key=PLAN_KEY, state='completed')
    if row is None:
        raise ValueError(localized_message('创作方案不存在'))
    plan = CreationPlan.model_validate(row.result)
    if novel_id is not None and plan.novel_id != novel_id:
        raise ValueError(localized_message('创作方案不属于当前项目'))
    return plan


async def validate_sources(plan):
    for evidence in plan.chapters:
        chapter = await Chapter.get_or_none(id=evidence.chapter_id, novel_id=plan.novel_id)
        if chapter is None or chapter_version(chapter) != evidence.version:
            raise ValueError(localized_message('方案引用的原文已变化，请重新规划并确认'))


async def validate_objects(plan, keys=None, chapter_ids=None):
    models = {'asset': Asset, 'variant': AssetVariant, 'scene': Scene}
    for key, version in plan.object_versions.items():
        if keys is not None and key not in keys:
            continue
        kind, identifier = key.split(':')
        target = await models[kind].get_or_none(id=int(identifier))
        if target is None or await object_version(target) != version:
            raise ValueError(localized_message('方案涉及的对象已有新修改，请重新规划并确认'))
    for chapter_id, versions in plan.chapter_scenes.items():
        if chapter_ids is not None and int(chapter_id) not in chapter_ids:
            continue
        current = {str(row.id): await object_version(row) for row in await Scene.filter(chapter_id=int(chapter_id))}
        if current != versions:
            raise ValueError(localized_message('方案涉及的分镜已有新修改，请重新规划并确认'))


class CreationPlanner:
    def __init__(self, execution, source):
        self.execution = execution
        self.source = source
        self.novel_id = execution.params['novel_id']

    async def prepare(self, request):
        existing = await AgentOperation.get_or_none(task_id=self.execution.params['task_id'], key=PLAN_KEY, state='completed')
        if existing:
            return CreationPlan.model_validate(existing.result)
        if request.write_scope == 'read_only':
            raise ValueError(localized_message('只读请求不能生成'))
        chapters = await Chapter.filter(novel_id=self.novel_id).order_by('number').values('id', 'number', 'name')
        assets = await Asset.filter(novel_id=self.novel_id, asset_type__in=[1, 2, 3]).values(
            'id', 'canonical_name', 'source_chapters', 'description')
        scenes = await Scene.filter(chapter__novel_id=self.novel_id).values('id', 'chapter_id', 'sequence', 'description')
        variants = await AssetVariant.filter(asset__novel_id=self.novel_id).values('id', 'asset_id', 'name', 'chapter_numbers')
        brief = await self.execution.generate('planning_request', {
            'user_message': request.message, 'selection': request.model_dump(mode='json'),
            'chapters': chapters, 'assets': assets, 'variants': variants, 'scenes': scenes,
        }, CreationBrief)
        if not brief.operations:
            return None
        if brief.missing_material:
            raise ValueError(localized_message('创作所需资料不完整：{p0}', p0='；'.join(brief.missing_material)))
        if brief.project_scope_quote and brief.project_scope_quote not in request.message:
            raise ValueError(localized_message('跨章范围必须引用本轮原话'))
        chapter_ids = {row['id'] for row in chapters}
        by_number = {row['number']: row['id'] for row in chapters}
        if not set(brief.read_chapter_numbers) <= by_number.keys():
            raise ValueError(localized_message('要求阅读的章节尚未导入，无法完整比较'))
        brief.read_chapter_ids = list(dict.fromkeys([*brief.read_chapter_ids, *[by_number[number] for number in brief.read_chapter_numbers]]))
        if brief.write_selection == 'project':
            if not brief.project_scope_quote:
                raise ValueError(localized_message('全项目生成必须提供明确范围原话'))
            brief.write_chapter_ids = [row['id'] for row in chapters]
        if not set(brief.read_chapter_ids + brief.write_chapter_ids) <= chapter_ids:
            raise ValueError(localized_message('创作要求中的章节不存在'))
        if not brief.project_scope_quote and request.write_scope != 'project':
            if set(brief.write_chapter_ids) - {request.chapter_id}:
                raise ValueError(localized_message('方案超出本轮章节范围'))
        if len({r.id for r in brief.requirements}) != len(brief.requirements) or not brief.requirements:
            raise ValueError(localized_message('创作要求缺失或重复'))
        for requirement in brief.requirements:
            if requirement.source_quote not in request.message or not set(requirement.chapter_ids) <= chapter_ids:
                raise ValueError(localized_message('创作要求必须有本轮原话和实际章节依据'))
        # Target chapters are also read, so source-version checks cover generated content.
        read_ids = list(dict.fromkeys([*brief.read_chapter_ids, *brief.write_chapter_ids]))
        loader = CreationSourceLoader(self.execution)
        evidence = await loader.read(read_ids, [r.model_dump() for r in brief.requirements])
        async def validate_draft(draft):
            from services.creation_agent.plan_normalization import coalesce_storyboards
            draft.steps, _ = coalesce_storyboards(draft.steps, {row['id']: row['number'] for row in chapters}, self.execution.language)
            candidate = CreationPlan(**draft.model_dump(), novel_id=self.novel_id,
                source_message_id=self.source.id, original_request=request.model_dump(mode='json'),
                brief=brief, chapters=evidence)
            await self.validate_steps(candidate, request)
            await loader.excerpts([source for step in candidate.steps for source in step.sources], evidence, strict_refs=True)
            draft.steps = candidate.steps
        from prompts.creation_plan import plan_reference_instructions
        draft = await self.execution.generate('creation_planning', {
            'user_message': request.message, 'brief': brief.model_dump(), 'selection': request.model_dump(mode='json'),
            'chapters': [item.model_dump() for item in evidence], 'assets': assets, 'variants': variants, 'scenes': scenes,
        }, CreationPlanDraft, output_validator=validate_draft,
            additional_instructions=plan_reference_instructions(self.execution.language))
        from services.creation_agent.plan_normalization import coalesce_storyboards
        draft.steps, _ = coalesce_storyboards(draft.steps, {row['id']: row['number'] for row in chapters}, self.execution.language)
        plan = CreationPlan(**draft.model_dump(), novel_id=self.novel_id, source_message_id=self.source.id,
            original_request=request.model_dump(mode='json'), brief=brief, chapters=evidence)
        await self.validate_steps(plan, request)
        plan.excerpts = await loader.excerpts([selection for step in plan.steps for selection in step.sources], evidence)
        for step in plan.steps:
            keys = []
            for variant in await AssetVariant.filter(id__in=step.variant_ids):
                plan.object_versions[f'variant:{variant.id}'] = await object_version(variant)
                keys.append(f'variant:{variant.id}')
            for asset_id in step.asset_ids:
                asset = await Asset.get(id=asset_id, novel_id=self.novel_id)
                plan.object_versions[f'asset:{asset.id}'] = await object_version(asset)
                keys.append(f'asset:{asset.id}')
            if step.operation in {'assets', 'storyboard'}:
                chapter = await Chapter.get(id=step.target_id)
                for asset in await Asset.filter(novel_id=self.novel_id):
                    if chapter.number in (asset.source_chapters or []):
                        plan.object_versions[f'asset:{asset.id}'] = await object_version(asset)
                        keys.append(f'asset:{asset.id}')
                plan.chapter_scenes[str(chapter.id)] = {
                    str(row.id): await object_version(row) for row in await Scene.filter(chapter_id=chapter.id)}
            elif step.target_id:
                kind, model = ('variant', AssetVariant) if step.variant_id else ('asset', Asset) if step.operation == 'image' else ('scene', Scene)
                obj = await model.get(id=step.variant_id or step.target_id)
                plan.object_versions[f'{kind}:{obj.id}'] = await object_version(obj)
                keys.append(f'{kind}:{obj.id}')
                if step.operation == 'video':
                    from services.video.asset_resolver import normalize_selected_variant_ids, select_asset_variant
                    await obj.fetch_related('chapter', 'assets__variants')
                    selected = normalize_selected_variant_ids((obj.metadata or {}).get('asset_variant_ids'))
                    for asset in obj.assets:
                        plan.object_versions[f'asset:{asset.id}'] = await object_version(asset)
                        keys.append(f'asset:{asset.id}')
                        variant = select_asset_variant(asset, obj.chapter.number, selected)
                        if variant:
                            plan.object_versions[f'variant:{variant.id}'] = await object_version(variant)
                            keys.append(f'variant:{variant.id}')
            plan.object_scopes[step.id] = list(dict.fromkeys(keys))
        await AgentOperation.create(task_id=self.execution.params['task_id'], key=PLAN_KEY, state='completed', result=plan.model_dump(mode='json'))
        task = await AiTask.get(id=self.execution.params['task_id'])
        task.request_params = {**task.request_params, 'has_creation_plan': True}
        await task.save(update_fields=['request_params'])
        self.execution.params['has_creation_plan'] = True
        await plan_activity(self.execution, 'planned', localized_message('创作方案已准备'), detail=plan.summary)
        return plan

    async def validate_steps(self, plan, request):
        from schemas.agent_workflow import ProductionIntent
        from services.creation_agent.intent_tools import validate_intent_scope
        by_id = {step.id: step for step in plan.steps}
        requirements = {item.id: item for item in plan.brief.requirements}
        if set(requirements) - {identifier for step in plan.steps for identifier in step.requirement_ids}:
            raise ValueError(localized_message('方案遗漏了用户的创作要求'))
        for operation in set(plan.brief.operations) & {'assets', 'storyboard'}:
            covered = {step.target_id for step in plan.steps if step.operation == operation}
            if not set(plan.brief.write_chapter_ids) <= covered:
                raise ValueError(localized_message('方案遗漏了要求生成的章节'))
        for step in plan.steps:
            if step.mode == 'regenerate' and step.operation not in {'image', 'video'}:
                raise ValueError(localized_message('重新生成模式仅适用于图片或视频'))
            if step.operation not in plan.brief.operations and not (step.operation == 'assets' and 'storyboard' in plan.brief.operations):
                raise ValueError(localized_message('方案包含未请求的生产操作'))
            if not set(step.requirement_ids) <= requirements.keys():
                raise ValueError(localized_message('步骤引用了不存在的创作要求'))
            prerequisite = step.operation == 'assets' and step.target_id in plan.brief.read_chapter_ids and any(
                step.id in following.depends_on and following.operation == 'storyboard' for following in plan.steps)
            if step.operation in {'assets', 'storyboard'} and step.target_id not in plan.brief.write_chapter_ids and not prerequisite:
                raise ValueError(localized_message('参考章节不等于可修改章节'))
            if step.source_step:
                expected = 'assets' if step.operation == 'image' else 'storyboard'
                if by_id[step.source_step].operation != expected:
                    raise ValueError(localized_message('上游步骤没有对应类型的输出'))
            else:
                scoped = request.model_copy(update={'write_scope': 'project', 'targets': []}) if plan.brief.project_scope_quote or prerequisite else request
                await validate_intent_scope(ProductionIntent(operation=step.operation, target_id=step.target_id,
                    variant_id=step.variant_id, request_id=uuid5(UUID(self.execution.params['task_id']), step.id)),
                    request=scoped, novel_id=self.novel_id)
            if step.operation in {'assets', 'storyboard'}:
                for rid in step.requirement_ids:
                    if requirements[rid].chapter_ids and step.target_id not in requirements[rid].chapter_ids:
                        raise ValueError(localized_message('步骤包含其他章节的专属要求'))
            if await Asset.filter(id__in=step.asset_ids, novel_id=self.novel_id, asset_type__in=[1, 2, 3]).count() != len(set(step.asset_ids)):
                raise ValueError(localized_message('方案引用了不存在的资产'))
            selected_variants = await AssetVariant.filter(id__in=step.variant_ids, asset__novel_id=self.novel_id)
            if len(selected_variants) != len(step.variant_ids) or len({row.asset_id for row in selected_variants}) != len(selected_variants):
                raise ValueError(localized_message('方案中的形态不存在或同一资产选择了多个形态'))
            step.asset_ids = list(dict.fromkeys([*step.asset_ids, *[row.asset_id for row in selected_variants]]))


async def plan_proposal(task_id):
    task = await AiTask.get(id=task_id)
    if task.task_type != 7:
        return None
    plan = await load_plan(task_id)
    revision = fingerprint(plan.model_dump(mode='json'))
    confirmed = await AgentOperation.get_or_none(task_id=task_id, key='creation:confirmed', state='completed')
    if confirmed:
        return None
    original = plan.original_request
    return {'confirmation_request_id': str(uuid5(UUID(str(task_id)), 'plan:' + revision)),
        'message': localized_message('确认执行创作方案'), 'plan_confirmation': {'task_id': str(task_id), 'revision': revision},
        'summary': plan.summary, 'read_chapters': [f"{c.number} · {c.name}" for c in plan.chapters],
        'labels': [{'operation': step.operation, 'target_label': step.label,
                    'mode': step.mode, 'instructions': step.instructions} for step in plan.steps],
        'intents': [], 'chapter_id': original.get('chapter_id'), 'targets': [],
        'write_scope': original.get('write_scope', 'chapter'), 'model_config_id': original.get('model_config_id')}


async def confirmed_plan(conversation, confirmation):
    source = await AgentMessage.get_or_none(task_id=confirmation.task_id, role='user', conversation_id=conversation.id)
    if source is None:
        raise HTTPException(404, localized_message('当前会话不存在该创作方案'))
    try:
        plan = await load_plan(confirmation.task_id, novel_id=conversation.novel_id)
        if fingerprint(plan.model_dump(mode='json')) != confirmation.revision:
            raise ValueError(localized_message('方案版本已变化，请核对最新方案'))
        await validate_sources(plan)
        await validate_objects(plan)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return plan
