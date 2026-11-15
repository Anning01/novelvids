"""Storyboard model orchestration with bounded continuation batches."""

from utils.messages import localized_message

import json
from typing import Any

from openai import AsyncOpenAI

from prompts.storyboard import build_storyboard_messages, visible_storyboard_assets
from prompts.asset_introductions import asset_introduction_requirement
from schemas.scene import SceneEntity, Storyboard
from services.llm.json_output import (
    JsonCompletionTruncatedError,
    create_json_completion,
    completion_usage,
)
from services.storyboard.chunking import NarrativeChunker, screenplay_sections
from services.storyboard.strategies import storyboard_strategy_factory
from services.storyboard.validation import validate_storyboard_duration


def _message_characters(messages: list[dict[str, str]]) -> int:
    schema_characters = len(
        json.dumps(Storyboard.model_json_schema(), ensure_ascii=False)
    )
    return sum(len(message["content"]) for message in messages) + schema_characters


def _usage_values(completion: Any) -> dict[str, int]:
    return completion_usage(completion)


def _aggregate_metadata(completions: list[Any]) -> dict[str, Any]:
    last_completion = completions[-1]
    usage_totals: dict[str, int] = {}
    response_ids: list[str] = []
    refusal: str | None = None
    for completion in completions:
        response_id = getattr(completion, "id", None)
        if response_id:
            response_ids.append(response_id)
        for key, value in _usage_values(completion).items():
            usage_totals[key] = usage_totals.get(key, 0) + value
        choices = getattr(completion, "choices", [])
        if choices:
            refusal = getattr(choices[0].message, "refusal", None) or refusal

    metadata: dict[str, Any] = {
        "model": getattr(last_completion, "model", None),
        "response_id": getattr(last_completion, "id", None),
        "response_ids": response_ids,
        "created": getattr(last_completion, "created", None),
        "system_fingerprint": getattr(last_completion, "system_fingerprint", None),
        "batch_count": len(completions),
    }
    if usage_totals:
        metadata["usage"] = usage_totals
    if refusal:
        metadata["refusal"] = refusal
    return metadata


async def generate_storyboard(
    client: AsyncOpenAI,
    long_text: str,
    entities: list[SceneEntity],
    model: str,
    supports_json_output: bool = False,
    prompt_language: str = "zh",
    max_context_characters: int | None = None,
    thinking: str | None = None,
    max_tokens: int | None = None,
    storyboard_strategy: str | None = None,
    creative_constraints: list[dict] | None = None,
    previously_seen_assets: list[str] | None = None,
    scene_layouts: dict | None = None,
    introduction_descriptions: dict[str, str] | None = None,
    shot_duration_range: list[int] | None = None,
    episode_pacing: dict | None = None,
    episode_max_seconds: int | None = None,
) -> tuple[Storyboard, dict[str, Any]]:
    """Generate fresh bounded calls and carry only a continuity summary."""
    from services.creation_agent.skill_execution import current_execution
    execution = current_execution.get()
    seen_assets = list(dict.fromkeys(previously_seen_assets or []))
    if execution:
        from schemas.agent_workflow import SkillStoryboard, StructuredSkillStoryboard
        modern = "storyboard_contract" in execution.snapshot.contents
        facts = {'chapter': long_text,
            'entities': [entity.model_dump() for entity in entities], 'strategy': storyboard_strategy,
            'constraints': creative_constraints or []}
        if scene_layouts:
            facts["scene_layouts"] = scene_layouts
        facts["episode_pacing"] = episode_pacing or {"preset": "smart"}
        if episode_max_seconds is not None:
            facts["episode_max_seconds"] = episode_max_seconds
        if duration_range := execution.params.get("shot_duration_range", shot_duration_range):
            facts["shot_duration_range"] = duration_range
        sections = screenplay_sections(long_text)
        shots = []
        scene_numbers = []
        layouts = dict(scene_layouts or {})
        # Missing flag belongs to an older frozen task; preserve its replay keys.
        generate_blocking_maps = execution.params.get('generate_blocking_maps', True)
        if not generate_blocking_maps:
            facts['generate_blocking_maps'] = False
        plan_continuations = generate_blocking_maps and modern and "blocking_guide" in execution.snapshot.contents
        for index, (scene_number, content) in enumerate(sections):
            scene_facts = {**facts, 'chapter': content}
            if layouts:
                scene_facts["scene_layouts"] = dict(layouts)
            if scene_number:
                scene_facts.update(segment=f'screenplay:{index}:{scene_number}', source_scene_number=scene_number)
            requirement = asset_introduction_requirement(entities, seen_assets, prompt_language, introduction_descriptions)
            if plan_continuations and scene_number:
                from prompts.storyboard import scene_continuity_instruction
                requirement = "\n".join(filter(None, (requirement, scene_continuity_instruction(prompt_language))))
            options = {"additional_instructions": requirement} if requirement else {}
            if scene_number:
                options['activity_label'] = localized_message('生成场次 {p0} 的分镜', p0=scene_number)
            batch = await execution.generate('storyboard', scene_facts, StructuredSkillStoryboard if modern else SkillStoryboard, **options)
            previous = None
            for part, shot in enumerate(batch.shots, 1):
                if plan_continuations:
                    from services.storyboard.blocking_plans import ending_state, place_shot
                    continuation = part > 1 and (scene_number is not None or shot.duration_split_part is not None)
                    if continuation:
                        shot = shot.model_copy(update={"duration_split_part": part})
                        shot = await place_shot(execution, shot, entities, layouts, previous, content,
                                                f'blocking:{index}:{part}', activity_label=localized_message(
                                                    '场次 {p0} · 补充第 {p1}/{p2} 镜空间定位图',
                                                    p0=scene_number or index + 1, p1=part, p2=len(batch.shots)))
                    else:
                        shot = shot.model_copy(update={"blocking_map": None, "duration_split_part": None})
                    previous = ending_state(shot)
                elif not generate_blocking_maps:
                    shot = shot.model_copy(update={'blocking_map': None, 'duration_split_part': None})
                shots.append(shot.model_copy(update={"sequence": len(shots) + 1}))
                scene_numbers.append(scene_number)
                for name in visible_storyboard_assets(shot, entities):
                    if name not in seen_assets:
                        seen_assets.append(name)
        result = SkillStoryboard(shots=shots) if not modern else StructuredSkillStoryboard(shots=shots)
        if modern:
            from services.storyboard.validation import prepare_skill_storyboard
            result = prepare_skill_storyboard(result, execution.snapshot, prompt_language, entities,
                                               storyboard_strategy or "cinematic", scene_layouts=scene_layouts)
        return result, {'model': execution.params['assistant_model_config_id'], 'batch_count': len(sections), 'usage': {},
                        'source_scene_numbers': scene_numbers}
    strategy = storyboard_strategy_factory.resolve(storyboard_strategy)
    fixed_messages = build_storyboard_messages(
        "",
        entities,
        prompt_language,
        strategy=strategy,
        creative_constraints=creative_constraints or [],
        previously_seen_assets=seen_assets,
        introduction_descriptions=introduction_descriptions,
        shot_duration_range=shot_duration_range,
    )
    chunker = NarrativeChunker.for_context_limit(
        max_context_characters,
        _message_characters(fixed_messages),
    )
    chunks = [(number, chunk) for number, content in screenplay_sections(long_text) for chunk in chunker.split(content)]
    scene_numbers = []
    shots = []
    completions: list[Any] = []
    batch_index = 0

    while batch_index < len(chunks):
        number, content = chunks[batch_index]
        previous_shot = shots[-1] if shots and scene_numbers[-1] == number else None
        messages = build_storyboard_messages(
            content,
            entities,
            prompt_language,
            batch_index=batch_index,
            batch_count=len(chunks),
            next_sequence=len(shots) + 1,
            previous_shot=previous_shot,
            strategy=strategy,
            creative_constraints=creative_constraints or [],
            previously_seen_assets=seen_assets,
            introduction_descriptions=introduction_descriptions,
            shot_duration_range=shot_duration_range,
        )
        try:
            batch_storyboard, completion = await create_json_completion(
                client,
                model=model,
                messages=messages,
                response_model=Storyboard,
                prompt_language=prompt_language,
                supports_json_output=supports_json_output,
                timeout=600,
                thinking=thinking,
                max_tokens=max_tokens,
            )
        except JsonCompletionTruncatedError:
            retry_chunks = chunker.split_for_retry(content)
            if len(retry_chunks) <= 1:
                raise
            chunks[batch_index : batch_index + 1] = [(number, piece) for piece in retry_chunks]
            continue

        if number is not None and not batch_storyboard.shots:
            raise ValueError(localized_message('分镜模型未返回任何批次结果'))
        for shot in batch_storyboard.shots:
            scene_numbers.append(number)
            validate_storyboard_duration(shot, shot_duration_range)
            shots.append(shot.model_copy(update={"sequence": len(shots) + 1}))
            for name in visible_storyboard_assets(shot, entities):
                if name not in seen_assets:
                    seen_assets.append(name)
        completions.append(completion)
        batch_index += 1

    if not completions:
        raise ValueError(localized_message('分镜模型未返回任何批次结果'))
    return Storyboard(shots=shots), {**_aggregate_metadata(completions), "source_scene_numbers": scene_numbers}
