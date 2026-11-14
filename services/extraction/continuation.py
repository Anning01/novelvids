"""Finish truncated chapter designs with independently checkpointed asset outputs."""
from models.agent_operation import AgentOperation
from prompts.extraction import single_asset_instructions
from services.creation_agent.plan_sources import fingerprint, plan_activity
from services.extraction.cast import read_chapter_cast
from services.extraction.extractor import AssetExtractionResult, validate_required_design_assets
from utils.messages import localized_message

FIELDS = {1: 'persons', 2: 'scenes', 3: 'items'}


async def interrupted_inventory(execution, messages):
    """Reuse only a failed direct run with identical inputs, ownership and model."""
    p = execution.params
    if p.get('creation_step_id') != 'direct' or p.get('instruction_message_id'):
        return None
    input_key = f"extraction:inputs:{p['chapter_id']}:{execution.snapshot.revision}"
    current = await AgentOperation.get_or_none(task_id=p['task_id'], key=input_key)
    if current is None:
        return None
    rows = await AgentOperation.filter(key=input_key, state='completed', task__status=4,
        task__task_type=1).select_related('task').order_by('-id')
    for row in rows:
        previous = row.task.request_params
        keys = ('novel_id', 'chapter_id', 'team_id', 'user_id', 'assistant_model_config_id',
                'prompt_language', 'instruction_message_id', 'creation_step_id')
        if row.result != current.result or any(previous.get(key) != p.get(key) for key in keys):
            continue
        if previous.get('creation_plan_id') != str(row.task_id):
            continue
        failure = await AgentOperation.get_or_none(task_id=row.task_id, key='recovery:failure', state='completed')
        if not failure or not any(issue.get('code') == 'output_length' for issue in failure.result.get('issues', [])):
            continue
        # Incorporate source and registry changes, including catalog entries outside this chapter.
        model_key = 'model:assets:AssetExtractionResult:'
        identity = await AgentOperation.get_or_none(task_id=row.task_id, key='model-input:' + fingerprint(model_key))
        if not identity:
            continue
        signature = fingerprint(['assets', messages, execution.snapshot.revision, execution.language,
            p['assistant_model_config_id'], AssetExtractionResult.model_json_schema(), ''])
        if identity.result.get('revision') != signature:
            continue
        return row.task_id
    return None


async def finish_asset_inventory(extractor, execution, messages, previous_task=None):
    await plan_activity(execution, 'extraction-continuation', localized_message('正在分项完成本章资产'), status='running')
    required = list(extractor.required_assets)
    if not extractor.targeted:
        cast = await read_chapter_cast(execution, messages)
        required.extend(cast.required_assets())
    required.extend((kind, name) for kind, name, _ in extractor.required_variants)
    result = (extractor.initial_assets or AssetExtractionResult(persons=[], scenes=[], items=[])).model_copy(deep=True)
    for kind, name in dict.fromkeys(required):
        entries = getattr(result, FIELDS[kind])
        variants = [variant for k, n, variant in extractor.required_variants if (k, n) == (kind, name)]
        matching = [item for item in entries if item.name == name and item.base_traits.strip()]
        if matching and set(variants).issubset({item.variant.name for item in matching if item.variant}):
            continue
        selection = {'category': kind, 'name': name, 'required_variants': variants}
        segment = 'entry:' + fingerprint(selection)
        async def validate(batch):
            validate_required_design_assets(batch, ((kind, name),))
            if any((k, item.name) != (kind, name) for k, field in FIELDS.items() for item in getattr(batch, field)):
                raise ValueError('Return only the selected asset with its canonical name and category')
            actual = {item.variant.name for item in getattr(batch, FIELDS[kind]) if item.variant}
            if (extractor.targeted and actual) or not set(variants).issubset(actual):
                raise ValueError('Follow the selected appearance requirements')

        saved = await AgentOperation.get_or_none(task_id=previous_task,
            key=f'model:assets:AssetExtractionResult:{segment}', state='completed') if previous_task else None
        if saved:
            batch = AssetExtractionResult.model_validate(saved.result)
            await validate(batch)
            await AgentOperation.get_or_create(task_id=execution.params['task_id'],
                key=saved.key, defaults={'state': 'completed', 'result': saved.result})
        else:
            batch = await execution.generate('assets', {'segment': segment, 'source_messages': messages, 'selection': selection},
                AssetExtractionResult, additional_instructions=single_asset_instructions(execution.language),
                asset_scope=((kind, name),), output_validator=validate)
        await validate(batch)
        entries[:] = [item for item in entries if item.name != name] + getattr(batch, FIELDS[kind])
        await plan_activity(execution, segment, localized_message('已完成资产设定'), detail=name)
    await extractor._validate_coverage(result)
    await plan_activity(execution, 'extraction-continuation', localized_message('已完成本章资产清单'))
    return result
