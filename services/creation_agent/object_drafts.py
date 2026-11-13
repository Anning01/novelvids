"""Keep large generated content out of chat tool arguments; share the normal writer."""

from pydantic import BaseModel, ConfigDict, Field

from models.agent_operation import AgentOperation
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.plan_sources import fingerprint


class AssetDesignDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=1, max_length=8000)
    visual_fields: dict[str, str] = Field(default_factory=dict)
    design: str = Field(default='', max_length=32000, description='完整视觉设计正文')


async def revise_object(service, execution, target, instructions, tool_call_id):
    from models.creation_agent import PromptChange
    from services.creation_agent.operation_receipts import execute_step
    await service.authorize()
    obj = await service.creative_target(target.kind, target.id)
    await service.scope.target(target.kind, obj)
    key = 'draft-request:' + fingerprint(tool_call_id)
    input_hash = fingerprint([target.model_dump(), instructions])
    receipt, _ = await AgentOperation.get_or_create(task_id=service.task_id, key=key,
        defaults={'result': {'input_hash': input_hash}})
    if receipt.result.get('input_hash') != input_hash:
        raise ValueError('同一工具调用不能对应不同的修改要求')

    async def generate_and_save():
        change = await _revise_object(service, execution, target, instructions, tool_call_id)
        return {'input_hash': input_hash, 'change_id': change.id}

    result = await execute_step(service.task_id, key, generate_and_save)
    return await PromptChange.get(id=result['change_id'], task_id=service.task_id)


async def _revise_object(service, execution, target, instructions, tool_call_id):
    await service.authorize()
    obj = await service.creative_target(target.kind, target.id)
    await service.scope.target(target.kind, obj)
    current = (await service.read([target], use_cache=True))[0]
    kind, layout = ('storyboard', 'character_turnaround') if target.kind == 'scene' else await service.prompt_standards.asset_kind(obj)
    contract = await service.prompt_standards.contract(kind, layout)
    facts = {'target': current, 'instructions': instructions, 'contract': contract}
    facts['segment'] = 'object:' + fingerprint(facts)
    draft_key = 'draft:' + fingerprint([target.model_dump(), instructions, facts['segment']])
    saved = await AgentOperation.get_or_none(task_id=service.task_id, key=draft_key, state='completed')
    if saved:
        changes = CreationChangeSet.model_validate(saved.result['changes'])
    else:
        if target.kind == 'scene':
            from schemas.agent_workflow import StructuredSkillStoryboard
            from services.creation_agent.tools import PromptEditService
            from services.storyboard.validation import prepare_skill_storyboard, validate_storyboard_duration
            entities = await PromptEditService._entities(obj)
            strategy = (await service.prompt_standards.context())['strategy'].key
            facts.update(entities=[entity.model_dump() for entity in entities], shot_count=1,
                         shot_duration_range=[obj.duration, obj.duration], strategy=strategy)
            output = await execution.generate('storyboard', facts, StructuredSkillStoryboard)
            if len(output.shots) != 1:
                raise ValueError('单个分镜修改只能返回一个镜头')
            validate_storyboard_duration(output.shots[0], [obj.duration, obj.duration])
            output = prepare_skill_storyboard(output, execution.snapshot, execution.language, entities, strategy)
            fields = {'prompt': output.shots[0].prompt}
            operation = {'operation': 'update_scene', 'scene_id': target.id, 'fields': fields}
        else:
            from prompts.creation_standards import render_asset_design
            render_kind = 'group' if kind == 'person' and layout == 'group_portrait' else kind

            def render(output):
                return render_asset_design(output.design or output.description, output.visual_fields,
                    render_kind, execution.snapshot, execution.language, contract['aspect_ratio'])

            async def validate(output):
                await service.prompt_standards.prepare_asset(render(output), asset_type={
                    'person': 1, 'scene': 2, 'item': 3}[kind], layout=layout)

            output = await execution.generate('structured', facts, AssetDesignDraft, output_validator=validate)
            operation = {'operation': 'update_setting', 'target': target.model_dump(),
                         'fields': {'description': output.description, 'prompt': render(output)}}
        changes = CreationChangeSet.model_validate({'operations': [operation]})
        await AgentOperation.create(task_id=service.task_id, key=draft_key, state='completed',
            result={'changes': changes.model_dump(mode='json'), 'target': target.model_dump(),
                    'version': service.observed[(target.kind, target.id)], 'protocol': execution.snapshot.revision})
    return await service.apply(changes, tool_call_id=tool_call_id)
