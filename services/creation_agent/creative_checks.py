"""Evidence-based semantic checking before persistence, with one bounded repair."""

from models.agent_operation import AgentOperation
from prompts.creation_plan import correction_instructions
from schemas.creation_plan import CreativeCheck
from services.creation_agent.plan_sources import plan_activity
from utils.messages import localized_message
from pydantic import BaseModel


class CreativeCandidateRejected(ValueError):
    pass


class ExistingCreationContent(BaseModel):
    objects: list[dict]


async def check_preserved_result(execution, step, target_id, result):
    from services.creation_agent.step_context import step_context
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    context = await step_context(execution.params)
    if context is None or not (context.requirements or context.constraints):
        return
    if step.operation == 'storyboard':
        objects = await Scene.filter(id__in=result['scene_ids']).order_by('sequence').values('sequence', 'prompt', 'prompt_params')
    elif step.operation == 'image':
        target = await AssetVariant.get(id=step.variant_id) if step.variant_id else await Asset.get(id=target_id)
        objects = [{'prompt': target.base_traits, 'description': target.description}]
    else:
        target = await Scene.get(id=target_id)
        objects = [{'prompt': target.prompt, 'prompt_params': target.prompt_params}]
    report = await check_candidate(execution, step.operation, {'segment': f'preserved:{target_id}'},
        ExistingCreationContent(objects=objects), context, 0)
    if not report.passed:
        raise CreativeCandidateRejected(localized_message('已有成果未落实新要求，已保留原内容；请在新方案中明确调整：{p0}',
            p0='；'.join(report.issues + [item.detail for item in report.findings if not item.passed])))


async def check_candidate(execution, skill, facts, candidate, context, attempt):
    segment = str(facts.get('segment', '')) if isinstance(facts, dict) else ''
    report = await execution._generate('creative_check', {
        'segment': f'{skill}:{segment}:check:{attempt}', 'step_context': context.model_dump(mode='json'),
        'input': facts, 'candidate': candidate.model_dump(mode='json'),
    }, CreativeCheck)
    expected = {item.id for item in context.requirements}
    actual = [item.requirement_id for item in report.findings]
    if set(actual) != expected or len(actual) != len(expected):
        raise CreativeCandidateRejected(localized_message('检查结果没有逐条覆盖创作要求'))
    if any(item.passed and not item.location.strip() for item in report.findings):
        raise CreativeCandidateRejected(localized_message('检查结果缺少候选内容依据'))
    await AgentOperation.update_or_create(task_id=execution.params['task_id'], key=f'creative-check:{skill}:{segment}:{attempt}',
        defaults={'state': 'completed', 'result': {'candidate': candidate.model_dump(mode='json'), 'check': report.model_dump(mode='json')}})
    await plan_activity(execution, f'check:{skill}:{segment}:{attempt}', localized_message('正在核对创作要求'),
        status='completed' if report.passed else 'failed', detail='；'.join(report.issues))
    return report


async def generate_checked(execution, skill, facts, output_type, options, context):
    candidate = await execution._generate(skill, facts, output_type, **options)
    report = await check_candidate(execution, skill, facts, candidate, context, 0)
    if report.passed:
        return candidate
    original_segment = facts.get('segment', '') if isinstance(facts, dict) else ''
    repaired_facts = {'segment': f'{original_segment}:creative-repair:1', 'original_input': facts,
        'candidate': candidate.model_dump(mode='json'), 'creative_check': report.model_dump(mode='json')}
    repaired_options = {**options, 'additional_instructions': options.get('additional_instructions', '') + '\n' + correction_instructions(execution.language)}
    candidate = await execution._generate(skill, repaired_facts, output_type, **repaired_options)
    report = await check_candidate(execution, skill, facts, candidate, context, 1)
    if not report.passed:
        raise CreativeCandidateRejected(localized_message('候选内容未通过创作要求检查，已保留候选，未覆盖原成果：{p0}',
            p0='；'.join(report.issues + [item.detail for item in report.findings if not item.passed])))
    return candidate
