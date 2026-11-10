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


def review_notes(report):
    notes = report.issues or [item.detail for item in report.findings if not item.passed]
    return list(dict.fromkeys(note for note in notes if note.strip())) or [localized_message('部分创作细节仍需完善，请查看已保存的分镜。')]


async def record_storyboard_review(execution, report):
    await AgentOperation.update_or_create(task_id=execution.params['task_id'], key='creative-review:storyboard',
        defaults={'state': 'completed', 'result': {'needs_revision': not report.passed,
            'notes': review_notes(report) if not report.passed else [], 'check': report.model_dump(mode='json')}})


async def check_preserved_result(execution, step, target_id, result):
    if step.operation == 'assets' and step.mode == 'fill_missing':
        # Extraction reuse already verifies source, rules and all saved designs locally.
        return
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
        if step.operation == 'storyboard':
            result.update(needs_revision=True, review_notes=review_notes(report))
            return
        raise CreativeCandidateRejected(localized_message('已有成果未落实新要求，已保留原内容；请在新方案中明确调整：{p0}',
            p0='；'.join(report.issues + [item.detail for item in report.findings if not item.passed])))


async def check_candidate(execution, skill, facts, candidate, context, attempt):
    segment = str(facts.get('segment', '')) if isinstance(facts, dict) else ''
    expected = {item.id for item in context.requirements}
    async def validate_report(report):
        actual = [item.requirement_id for item in report.findings]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError(localized_message('请逐条返回这些 requirement_id，不增不漏：{p0}', p0=', '.join(sorted(expected))))
        if any(item.passed and not item.location.strip() for item in report.findings):
            raise ValueError(localized_message('检查结果缺少候选内容依据'))
        if hasattr(candidate, 'shots'):
            available = {shot.sequence for shot in candidate.shots}
            if any(number not in available for item in report.findings for number in item.shot_sequences):
                raise ValueError('shot_sequences must reference existing candidate shots')
    review_facts = {
        'segment': f'{skill}:{segment}:check:{attempt}', 'step_context': context.model_dump(mode='json'),
        'input': facts, 'candidate': candidate.model_dump(mode='json'),
    }
    from prompts.storyboard_repair import review_locations
    report = await execution._generate('creative_check', review_facts, CreativeCheck, output_validator=validate_report,
        additional_instructions=review_locations(execution.language) if hasattr(candidate, 'shots') else '')
    try:
        await validate_report(report)
    except ValueError:
        # Old completed reports predate schema feedback; repair once under a
        # different key without altering their original receipt or charging it again.
        await execution.claim_repair('creative_check', 'review_schema')
        report = await execution._generate('creative_check', {**review_facts,
            'segment': review_facts['segment'] + ':schema-repair:1'}, CreativeCheck, output_validator=validate_report)
        await validate_report(report)
    await AgentOperation.update_or_create(task_id=execution.params['task_id'], key=f'creative-check:{skill}:{segment}:{attempt}',
        defaults={'state': 'completed', 'result': {'candidate': candidate.model_dump(mode='json'), 'check': report.model_dump(mode='json')}})
    advisory = skill == 'storyboard' and context.step.operation == 'storyboard'
    await plan_activity(execution, f'check:{skill}:{segment}:{attempt}',
        localized_message('检查发现待完善项') if advisory and not report.passed else localized_message('正在核对创作要求'),
        status='completed' if report.passed or advisory else 'failed', detail='；'.join(report.issues))
    return report


async def generate_checked(execution, skill, facts, output_type, options, context):
    candidate = None
    if context.coalesced_step_ids:
        from services.creation_agent.plan_sources import fingerprint
        revision = fingerprint(context.step.model_dump())[:20]
        persisted = await AgentOperation.filter(task_id=execution.params['task_id'], key='persist:storyboard', state='completed').exists()
        validated = await AgentOperation.get_or_none(task_id=execution.params['task_id'], key='coalesced:validated', state='completed')
        if persisted and (validated is None or validated.result.get('revision') != revision):
            raise CreativeCandidateRejected(localized_message('已有分段结果已保存，请先核对后再生成完整章节'))
        segment = facts.get('segment', '') if isinstance(facts, dict) else ''
        facts = {**facts, 'segment': f'{segment}:coalesced:{revision}'} if isinstance(facts, dict) else {
            'original_input': facts, 'segment': f'coalesced:{revision}'}
        seed_key = f'candidate-seed:{skill}:{revision}'
        seed = await AgentOperation.get_or_none(task_id=execution.params['task_id'], key=seed_key, state='completed')
        if seed is None:
            previous = await AgentOperation.filter(task_id=execution.params['task_id'],
                key__startswith=f'model:{skill}:{output_type.__name__}:', state='completed').exclude(key__contains='coalesced:').order_by('-id').first()
            if previous:
                seed, _ = await AgentOperation.get_or_create(task_id=execution.params['task_id'], key=seed_key,
                    defaults={'state': 'completed', 'result': {'candidate': previous.result, 'source_key': previous.key}})
        if seed:
            candidate = output_type.model_validate(seed.result['candidate'])
    if candidate is None:
        candidate = await execution._generate(skill, facts, output_type, **options)
    report = await check_candidate(execution, skill, facts, candidate, context, 0)
    if report.passed:
        if skill == 'storyboard' and context.step.operation == 'storyboard':
            await record_storyboard_review(execution, report)
        if context.coalesced_step_ids:
            await AgentOperation.update_or_create(task_id=execution.params['task_id'], key='coalesced:validated',
                defaults={'state': 'completed', 'result': {'revision': revision}})
        return candidate
    original_segment = facts.get('segment', '') if isinstance(facts, dict) else ''
    repaired_facts = {'segment': f'{original_segment}:creative-repair:1', 'original_input': facts,
        'candidate': candidate.model_dump(mode='json'), 'creative_check': report.model_dump(mode='json')}
    repaired_options = {**options, 'additional_instructions': options.get('additional_instructions', '') + '\n' + correction_instructions(execution.language)}
    targets = None
    if skill == 'storyboard' and hasattr(candidate, 'shots'):
        from prompts.storyboard_repair import semantic_repair
        targets = sorted({number for item in report.findings if not item.passed for number in item.shot_sequences})
        repaired_facts.pop('candidate')
        repaired_facts['storyboard_repair'] = {'candidate': candidate.model_dump(mode='json'), 'shot_sequences': targets}
        repaired_facts['repair_targets'] = [shot.model_dump(mode='json') for shot in candidate.shots if shot.sequence in targets]
        repaired_facts['read_only_neighbors'] = [shot.model_dump(mode='json') for shot in candidate.shots
            if shot.sequence not in targets and any(abs(shot.sequence - number) == 1 for number in targets)]
        repaired_options['additional_instructions'] = options.get('additional_instructions', '') + '\n' + semantic_repair(execution.language)
    if targets is None or targets:
        await execution.claim_repair(skill, 'creative_requirements')
        candidate = await execution._generate(skill, repaired_facts, output_type, **repaired_options)
        report = await check_candidate(execution, skill, facts, candidate, context, 1)
    # Editorial findings must not discard a usable text draft. Structural,
    # reference, timing and version checks still run before chapter persistence.
    advisory = skill == 'storyboard' and context.step.operation == 'storyboard'
    if advisory:
        await record_storyboard_review(execution, report)
    if not report.passed and not advisory:
        raise CreativeCandidateRejected(localized_message('候选内容未通过创作要求检查，已保留候选，未覆盖原成果：{p0}',
            p0='；'.join(report.issues + [item.detail for item in report.findings if not item.passed])))
    if context.coalesced_step_ids:
        await AgentOperation.update_or_create(task_id=execution.params['task_id'], key='coalesced:validated',
            defaults={'state': 'completed', 'result': {'revision': revision, 'needs_revision': not report.passed}})
    return candidate
