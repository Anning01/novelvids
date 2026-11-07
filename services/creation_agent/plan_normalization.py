"""Narrative sections share a chapter production job and its atomic persistence."""

from schemas.creation_plan import CreationPlanStep
from prompts.creation_plan import chapter_sections_instructions
from utils.messages import localized_message


def coalesce_storyboards(steps, chapter_numbers, language='zh'):
    grouped = {}
    for step in steps:
        key = ('storyboard', step.target_id) if step.operation == 'storyboard' else ('step', step.id)
        grouped.setdefault(key, []).append(step)
    aliases = {step.id: group[0].id for group in grouped.values() for step in group}
    groups = {group[0].id: [step.id for step in group] for group in grouped.values() if len(group) > 1}
    result = []
    for group in grouped.values():
        first = group[0]
        data = first.model_dump()
        if len(group) > 1:
            if len({step.mode for step in group}) != 1:
                raise ValueError(localized_message('同一章分镜不能同时使用不同处理方式，请合并为一个明确的章节任务'))
            data['instructions'] = chapter_sections_instructions([(step.label, step.instructions) for step in group], language)
            number = chapter_numbers.get(first.target_id)
            data['label'] = localized_message('第 {p0} 章完整分镜', p0=number, _language=language) if number is not None else localized_message('完整章节分镜', _language=language)
            for field in ('requirement_ids', 'asset_ids', 'variant_ids'):
                data[field] = list(dict.fromkeys(value for step in group for value in getattr(step, field)))
            sources = {}
            for step in group:
                for source in step.sources:
                    key = source.reference_id or (source.chapter_id, source.start, source.end)
                    sources.setdefault(key, source.model_dump())
            data['sources'] = list(sources.values())
        data['depends_on'] = list(dict.fromkeys(aliases[dep] for step in group for dep in step.depends_on if aliases[dep] != first.id))
        if data['source_step']:
            data['source_step'] = aliases[data['source_step']]
        result.append(CreationPlanStep.model_validate(data))
    ordered, done = [], set()
    while result:
        ready = next((step for step in result if set(step.depends_on) <= done), None)
        if ready is None:
            raise ValueError(localized_message('同章段落合并后存在循环依赖，请调整方案'))
        ordered.append(ready); done.add(ready.id); result.remove(ready)
    return ordered, groups


def execution_plan(plan, language='zh'):
    """Project old confirmed plans without changing the approved snapshot/hash."""
    projected = plan.model_copy(deep=True)
    projected.steps, groups = coalesce_storyboards(plan.steps, {chapter.chapter_id: chapter.number for chapter in plan.chapters}, language)
    for representative, members in groups.items():
        projected.object_scopes[representative] = list(dict.fromkeys(
            key for member in members for key in plan.object_scopes.get(member, [])))
    return projected, groups
