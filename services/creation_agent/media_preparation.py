"""Prepare the exact visible media prompt before any external submission."""

from uuid import UUID

from models.agent_operation import AgentOperation
from models.asset import Asset
from models.creation_agent import PromptChange
from schemas.agent_workflow import CompletePrompt, StructuredSkillStoryboard
from services.creation_agent.object_state import object_label, object_state, object_version, write_fields
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.prompt_standards import CreationPromptStandards
from services.creation_agent.step_context import step_context, validate_step_inputs
from services.creation_objects import CreationObjects, project_write
from utils.messages import localized_message


async def prepare_planned_media(execution, *, kind, target):
    context = await step_context(execution.params)
    if context is None:
        return
    key = 'prepare:media'
    previous = await AgentOperation.get_or_none(task_id=execution.params['task_id'], key=key, state='completed')
    if previous:
        await target.refresh_from_db()
        if await object_version(target) != previous.result['version']:
            raise ValueError(localized_message('准备后的提示词已被修改，请重新确认生成'))
        return
    await validate_step_inputs(execution.params)
    version = await object_version(target)
    old_prompt = target.prompt if kind == 'scene' else target.base_traits

    async def keep_prompt():
        async with project_write(execution.params['novel_id']):
            await validate_step_inputs(execution.params)
            await target.refresh_from_db()
            if await object_version(target) != version:
                raise ValueError(localized_message('检查期间提示词已被修改'))
            await AgentOperation.create(task_id=execution.params['task_id'], key=key, state='completed',
                result={'version': version, 'prompt': old_prompt})

    async def prepare():
        if kind == 'scene':
            from services.creation_agent.tools import PromptEditService
            from services.storyboard.validation import prepare_skill_storyboard, validate_storyboard_duration
            from services.creation_agent.prompt_edits import validate_prompt_dependencies
            from services.storyboard.strategies import storyboard_strategy_factory
            await target.fetch_related('chapter__novel')
            strategy = storyboard_strategy_factory.resolve(target.chapter.novel.storyboard_strategy).key
            entities = await PromptEditService._entities(target)
            facts = {'description': target.description, 'current_prompt': target.prompt,
                'structure': target.prompt_params, 'duration': target.duration,
                'entities': [entity.model_dump() for entity in entities], 'shot_count': 1,
                'strategy': strategy,
                'shot_duration_range': [target.duration, target.duration]}
            if old_prompt and context.step.mode != 'revise':
                from services.creation_agent.creative_checks import check_candidate, CreativeCandidateRejected
                check = await check_candidate(execution, 'video', facts, CompletePrompt(prompt=old_prompt), context, 0) if context.requirements or context.constraints else None
                if check and not check.passed:
                    raise CreativeCandidateRejected(localized_message('已有提示词未落实新要求，需要在方案中明确修改'))
                return await keep_prompt()
            candidate = await execution.generate('storyboard', facts, StructuredSkillStoryboard)
            if len(candidate.shots) != 1:
                raise ValueError(localized_message('单个视频只能修改当前分镜'))
            prepared = prepare_skill_storyboard(candidate, execution.snapshot, execution.language, entities,
                strategy).shots[0]
            validate_storyboard_duration(prepared, [target.duration, target.duration])
            validate_prompt_dependencies(prepared.prompt, entities)
            fields = {'prompt': prepared.prompt, 'prompt_params': {
                **target.prompt_params, **prepared.model_dump(exclude={'sequence', 'description', 'duration', 'prompt'}),
                'prompt_language': execution.language, 'rendering_version': 'agent-skills-v1'}}
        else:
            asset = await Asset.get(id=target.asset_id) if kind == 'variant' else target
            standards = CreationPromptStandards(execution.params['novel_id'])
            _, layout = await standards.asset_kind(target)
            facts = {'target': await object_label(target), 'description': target.description,
                'current_prompt': old_prompt, 'asset_type': asset.asset_type, 'reference_layout': layout,
                'aspect_ratio': execution.params.get('aspect_ratio')}
            if old_prompt and context.step.mode != 'revise':
                from services.creation_agent.creative_checks import check_candidate, CreativeCandidateRejected
                check = await check_candidate(execution, 'image', facts, CompletePrompt(prompt=old_prompt), context, 0) if context.requirements or context.constraints else None
                if check and not check.passed:
                    raise CreativeCandidateRejected(localized_message('已有提示词未落实新要求，需要在方案中明确修改'))
                return await keep_prompt()
            candidate = await execution.generate('image', facts, CompletePrompt)
            prompt = await standards.prepare_asset(candidate.prompt, asset_type=asset.asset_type, layout=layout)
            fields = {'base_traits': prompt}
        await execution.before_request()
        async with project_write(execution.params['novel_id']):
            await validate_step_inputs(execution.params)
            await target.refresh_from_db()
            if await object_version(target) != version:
                raise ValueError(localized_message('生成准备期间对象已被修改'))
            before = await object_state(target)
            await write_fields(CreationObjects(execution.params['novel_id']), target, fields)
            after = await object_state(target)
            changed = [field for field in fields if before.get(field) != after.get(field)]
            new_version = await object_version(target)
            if changed:
                await PromptChange.create(novel_id=execution.params['novel_id'],
                    task_id=UUID(execution.params['task_id']), tool_call_id=key, request_hash=fingerprint(fields),
                    changes=[{'kind': kind, 'target_id': target.id, 'target_label': await object_label(target),
                        'operation': 'update', 'before': {field: before.get(field) for field in changed},
                        'after': {field: after.get(field) for field in changed}, 'after_version': new_version,
                        'constraint_ids': [], 'recovery': {},
                        **({'asset_id': target.asset_id} if kind == 'variant' else {}),
                        **({'chapter_id': target.chapter_id} if kind == 'scene' else {})}])
            await AgentOperation.create(task_id=execution.params['task_id'], key=key, state='completed',
                result={'version': new_version, 'prompt': fields.get('prompt', fields.get('base_traits'))})
    await prepare()


async def validate_prepared_media(execution, target):
    if not execution.params.get('creation_plan_id'):
        return
    await validate_step_inputs(execution.params, include_target=False)
    await target.refresh_from_db()
    receipt = await AgentOperation.get_or_none(task_id=execution.params['task_id'], key='prepare:media', state='completed')
    if receipt is None or await object_version(target) != receipt.result['version']:
        raise ValueError(localized_message('实际生成内容与已准备内容不同，请重新确认'))
