"""Keep large generated content out of chat tool arguments; share the normal writer."""

from pydantic import BaseModel, ConfigDict, Field

from models.agent_operation import AgentOperation
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.plan_sources import fingerprint
from utils.messages import localized_message


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
    if target.kind == 'scene':
        from dataclasses import replace
        from prompts.text_tasks import scene_prompt_edit_method
        from schemas.text_task_contracts import scene_prompt_edit_contract
        from services.user_skills import snapshot_method
        current = (await service.read([target], full_prompt=True))[0]
        method = await snapshot_method(execution.params.get('user_id') or 0, 'storyboard')
        method = scene_prompt_edit_method(method)
        contract = scene_prompt_edit_contract()
        # Distinct revisions in one chat must not share the same model receipt.
        contract['name'] += '_' + fingerprint(tool_call_id)[:16]
        editor = replace(execution, params={**execution.params,
            'output_contract': contract, 'creative_method': method})
        output = await editor.generate_strict({'target': current, 'instructions': instructions, 'user_request': service.request.message})
        return await service.save_scene_prompts({target.id: output['prompt']}, tool_call_id)
    current = (await service.read([target], use_cache=True))[0]
    kind, layout = await service.prompt_standards.asset_kind(obj)
    contract = await service.prompt_standards.contract(kind, layout)
    facts = {'target': current, 'instructions': instructions, 'contract': contract}
    from services.story_memory.context import execution_context
    chapter_id = service.request.chapter_id
    if chapter_id is None:
        from models.asset import Asset
        from models.chapter import Chapter
        asset = await Asset.get(id=obj.asset_id if target.kind == 'variant' else obj.id)
        numbers = obj.chapter_numbers if target.kind == 'variant' else asset.source_chapters
        chapter = await Chapter.filter(novel_id=service.novel_id, number__in=numbers or []).order_by('number').first()
        chapter_id = chapter.id if chapter else None
    context = await execution_context(execution, chapter_id, purpose='assets')
    if context['enabled']:
        facts['story_memory'] = context
    facts['segment'] = 'object:' + fingerprint(facts)
    draft_key = 'draft:' + fingerprint([target.model_dump(), instructions, facts['segment']])
    saved = await AgentOperation.get_or_none(task_id=service.task_id, key=draft_key, state='completed')
    if saved:
        changes = CreationChangeSet.model_validate(saved.result['changes'])
    else:
        from prompts.creation_standards import render_asset_design
        render_kind = 'group' if kind == 'person' and layout == 'group_portrait' else kind

        def render(output):
            return render_asset_design(output.design or output.description, output.visual_fields,
                render_kind, execution.snapshot, execution.language, contract['aspect_ratio'])

        async def validate(output):
            await service.prompt_standards.prepare_asset(render(output), asset_type={
                'person': 1, 'scene': 2, 'item': 3}[kind], layout=layout)

        output = await execution.generate('structured', facts, AssetDesignDraft, output_validator=validate,
            activity_label=localized_message('修订资产设定'))
        operation = {'operation': 'update_setting', 'target': target.model_dump(),
                     'fields': {'description': output.description, 'prompt': render(output)}}
        changes = CreationChangeSet.model_validate({'operations': [operation]})
        await AgentOperation.create(task_id=service.task_id, key=draft_key, state='completed',
            result={'changes': changes.model_dump(mode='json'), 'target': target.model_dump(),
                    'version': service.observed[(target.kind, target.id)], 'protocol': execution.snapshot.revision})
    return await service.apply(changes, tool_call_id=tool_call_id)
