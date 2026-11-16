"""One contextual handoff shared by text and media production."""

from models.agent_operation import AgentOperation
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentMessage
from models.scene import Scene
from schemas.creation_plan import CreationStepContext
from services.creation_agent.memory import creation_memory
from services.creation_agent.plans import load_plan, validate_objects, validate_sources
from services.creation_agent.plan_normalization import execution_plan
from utils.messages import localized_message


async def step_context(params):
    if not params.get('creation_plan_id') or not params.get('creation_step_id'):
        return None
    plan = await load_plan(params['creation_plan_id'], novel_id=params['novel_id'])
    plan, groups = execution_plan(plan, params.get('prompt_language', 'zh'))
    step = next((item for item in plan.steps if item.id == params['creation_step_id']), None)
    if step is None:
        raise ValueError(localized_message('创作步骤不存在'))
    source = await AgentMessage.get(id=plan.source_message_id, role='user')
    upstream = {}
    asset_ids = set(step.asset_ids)
    for dependency in step.depends_on:
        row = await AgentOperation.get_or_none(task_id=params['creation_run_id'], key=f'plan-step:{dependency}', state='completed')
        if row is None or row.result.get('status') not in {'completed', 'skipped'}:
            raise ValueError(localized_message('前置创作步骤尚未完成'))
        upstream[dependency] = row.result
        asset_ids.update(row.result.get('asset_ids', []))
    chapter_id = params.get('chapter_id')
    if params.get('video_request'):
        scene = await Scene.get(id=params['video_request']['scene_id'])
        chapter_id = scene.chapter_id
        asset_ids.update(await scene.assets.all().values_list('id', flat=True))
    if params.get('asset_id'):
        asset_ids.add(params['asset_id'])
    chapter = await Chapter.get_or_none(id=chapter_id, novel_id=plan.novel_id) if chapter_id else None
    if chapter:
        for asset in await Asset.filter(novel_id=plan.novel_id, asset_type__in=[1, 2, 3]):
            if chapter.number in (asset.source_chapters or []):
                asset_ids.add(asset.id)
    assets = await Asset.filter(id__in=asset_ids, novel_id=plan.novel_id, asset_type__in=[1, 2, 3])
    projections = []
    for asset in assets:
        variants = await AssetVariant.filter(asset_id=asset.id).values('id', 'name', 'description', 'base_traits', 'chapter_numbers')
        projections.append({'id': asset.id, 'name': asset.canonical_name, 'aliases': asset.aliases,
            'description': asset.description, 'prompt': asset.base_traits, 'type': asset.asset_type,
            'analysis_source': (asset.metadata or {}).get('analysis_source'),
            'source_chapters': asset.source_chapters, 'variants': variants})
    selectors = {(item.chapter_id, item.start, item.end) for item in step.sources}
    constraints = await creation_memory.for_generation(chapter, assets) if chapter else []
    from schemas.creation_agent import AgentTarget, PromptStatusRequest
    target = (AgentTarget(kind='scene', id=params['video_request']['scene_id']) if params.get('video_request') else
        AgentTarget(kind='variant', id=params['variant_id']) if params.get('variant_id') else
        AgentTarget(kind='asset', id=params['asset_id']) if params.get('asset_id') else None)
    if target:
        target_rules = await creation_memory.applicable(plan.novel_id, PromptStatusRequest(chapter_id=chapter_id, targets=[target]))
        seen = {(rule['content'], str(rule['scope'])) for rule in constraints}
        constraints.extend(rule for rule in target_rules if (rule['content'], str(rule['scope'])) not in seen)
    return CreationStepContext(step=step, original_message=source.content,
        requirements=[item for item in plan.brief.requirements if item.id in step.requirement_ids],
        sources=[item for item in plan.excerpts if (item.chapter_id, item.start, item.end) in selectors],
        assets=projections, constraints=constraints, upstream_results=upstream,
        coalesced_step_ids=groups.get(step.id, []))


async def validate_step_inputs(params, *, include_target=True):
    if not params.get('creation_plan_id'):
        return
    plan = await load_plan(params['creation_plan_id'], novel_id=params['novel_id'])
    plan, _ = execution_plan(plan, params.get('prompt_language', 'zh'))
    await validate_sources(plan)
    step = next(item for item in plan.steps if item.id == params['creation_step_id'])
    keys = set(plan.object_scopes.get(step.id, [])) | {f'asset:{identifier}' for identifier in step.asset_ids}
    keys.update(f'variant:{identifier}' for identifier in step.variant_ids)
    # Versions produced by approved dependencies supersede the planning snapshot,
    # but subsequent user edits must still be detected.
    for dependency in step.depends_on:
        row = await AgentOperation.get_or_none(task_id=params['creation_run_id'], key=f'plan-step:{dependency}', state='completed')
        if row:
            plan.object_versions.update(row.result.get('object_versions', {}))
            if step.operation in {'assets', 'storyboard'}:
                keys.update(key for key in row.result.get('object_versions', {}) if key.startswith(('asset:', 'variant:')))
    target_id = (params.get('asset_id') if step.operation == 'image' else
        (params.get('video_request') or {}).get('scene_id') if step.operation == 'video' else None) or step.target_id
    variant_id = params.get('variant_id') or step.variant_id
    if not include_target:
        keys.discard(f'variant:{variant_id}' if variant_id else f'asset:{target_id}' if step.operation == 'image' else f'scene:{target_id}')
    if include_target and target_id:
        if step.operation == 'image':
            keys.add(f'variant:{variant_id}' if variant_id else f'asset:{target_id}')
        elif step.operation == 'video':
            keys.add(f'scene:{target_id}')
    if step.operation == 'video' and target_id:
        scene = await Scene.get(id=target_id, chapter__novel_id=plan.novel_id)
        keys.update(f'asset:{identifier}' for identifier in await scene.assets.all().values_list('id', flat=True))
    chapters = [step.target_id] if include_target and step.operation == 'storyboard' else []
    await validate_objects(plan, keys=keys, chapter_ids=chapters)


async def context_assets(params):
    context = await step_context(params)
    if context is None:
        return []
    return await Asset.filter(id__in=[item['id'] for item in context.assets], novel_id=params['novel_id'])
