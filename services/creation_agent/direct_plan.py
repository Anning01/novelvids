"""Already-authorized buttons use the same immutable handoff without a new gate."""

from models.agent_operation import AgentOperation
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentMessage
from models.scene import Scene
from schemas.creation_plan import CreationBrief, CreationPlan, CreationPlanStep, CreativeRequirement, ChapterEvidence
from services.creation_agent.object_state import object_version
from services.creation_agent.plan_sources import chapter_version
from services.creation_agent.plans import PLAN_KEY
from services.creation_agent.skill_execution import user_instruction


async def prepare_direct_plan(task, execution):
    params = execution.params
    operation = {1: 'assets', 2: 'image', 3: 'storyboard', 4: 'video'}[task.task_type]
    if task.task_type == 4 and params.get('operation') not in {None, 'video'}:
        return
    source = await AgentMessage.get(task=task, role='user')
    instruction = await user_instruction(params)
    original = instruction or source.content
    target_id = params.get('chapter_id') if operation in {'assets', 'storyboard'} else params.get('asset_id') if operation == 'image' else params['video_request']['scene_id']
    step = CreationPlanStep(id='direct', operation=operation, target_id=target_id, variant_id=params.get('variant_id'),
        mode='regenerate' if operation in {'image', 'video'} else 'revise' if 'replace_versions' in params else 'fill_missing', requirement_ids=['direct'],
        instructions=original, label=source.content)
    plan = CreationPlan(novel_id=params['novel_id'], source_message_id=params.get('instruction_message_id') or source.id,
        original_request=source.run_input, summary=source.content, steps=[step], brief=CreationBrief(operations=[operation],
        requirements=[CreativeRequirement(id='direct', instruction=original, source_quote=original, acceptance=original)] if instruction else []))
    chapter_id = params.get('chapter_id')
    if operation == 'video':
        chapter_id = (await Scene.get(id=target_id)).chapter_id
    if chapter_id:
        chapter = await Chapter.get(id=chapter_id)
        # The production handler supplies the full chapter to the model; no
        # separate reading call or fabricated reading-complete event is needed.
        plan.chapters = [ChapterEvidence(chapter_id=chapter.id, number=chapter.number, name=chapter.name,
            version=chapter_version(chapter), characters=len(chapter.content or ''), pages=[])]
    if operation == 'storyboard':
        plan.chapter_scenes[str(target_id)] = {str(row.id): await object_version(row) for row in await Scene.filter(chapter_id=target_id)}
    if operation in {'image', 'video'}:
        kind, model = ('variant', AssetVariant) if step.variant_id else ('asset', Asset) if operation == 'image' else ('scene', Scene)
        target = await model.get(id=step.variant_id or target_id)
        plan.object_versions[f'{kind}:{target.id}'] = await object_version(target)
        if operation == 'video':
            for asset in await target.assets.all():
                plan.object_versions[f'asset:{asset.id}'] = await object_version(asset)
    if chapter_id and operation in {'assets', 'storyboard'}:
        for asset in await Asset.filter(novel_id=params['novel_id']):
            if chapter.number in (asset.source_chapters or []):
                plan.object_versions[f'asset:{asset.id}'] = await object_version(asset)
    plan.object_scopes['direct'] = list(plan.object_versions)
    await AgentOperation.get_or_create(task=task, key=PLAN_KEY,
        defaults={'state': 'completed', 'result': plan.model_dump(mode='json')})
    params.update(creation_plan_id=str(task.id), creation_step_id='direct', creation_run_id=str(task.id))
    task.request_params = {**task.request_params, **{key: params[key] for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id')}}
    await task.save(update_fields=['request_params'])
