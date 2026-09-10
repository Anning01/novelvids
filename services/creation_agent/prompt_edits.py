"""Validate prompt dependencies and prepare edits without database side effects."""

import re
from collections.abc import Sequence

from prompts.storyboard import (
    entity_reference_names,
    format_storyboard_prompt,
    normalized_storyboard_reference_fields,
    normalize_storyboard_reference_text,
)
from prompts.storyboard_strategies import CINEMATIC_STORYBOARD_STRATEGY, StoryboardStrategyPrompt
from schemas.creation_agent import StoryboardPromptEdit, StoryboardVisualChanges
from schemas.scene import SceneEntity, SoraScenePromptConfig
from prompts.creation_agent import render_preserved_tracks


# Conservative checks for unresolved visual shorthand, not a general semantic judge.
_EXTERNAL_DESCRIPTION = re.compile(
    r"(?:镜头\s*[\d一二三四五六七八九十]+|上一镜头)(?:中|里)?的(?:女生|男生|女人|男人|女主|男主|人物)"
    r"|(?:外貌|服装|衣着|人物描述|环境描述|设定)\s*(?:同上|同前|照旧)"
)
_ENTITY_REFERENCE = re.compile(r"@\{([^{}]+)\}")
_LOCAL_HEADING = re.compile(r"(?m)^\s*(?:【|#{1,6}\s*)?镜头\s*(\d+)\s*(?:[·：:】]|$)")


def _validate_reference_syntax(text: str) -> None:
    if "@" in _ENTITY_REFERENCE.sub("", text):
        raise ValueError("素材引用格式无效，请只使用 @{完整实体名}")


def validate_image_prompt_edit(text: str, previous: str) -> None:
    _validate_reference_syntax(text)
    if _EXTERNAL_DESCRIPTION.search(text):
        raise ValueError("请完整描述当前图片，不要引用其他镜头的人物或同上")
    if set(_ENTITY_REFERENCE.findall(text)) != set(_ENTITY_REFERENCE.findall(previous)):
        raise ValueError("修改图片 Prompt 不能增删已有素材引用")


def validate_prompt_dependencies(text: str, entities: Sequence[SceneEntity]) -> None:
    _validate_reference_syntax(text)
    if _EXTERNAL_DESCRIPTION.search(text):
        raise ValueError("请展开当前请求内的人物与环境描述，不能依赖其他镜头或同上")
    names = {name for entity in entities for name in (entity.name, *entity.aliases)}
    references = {
        name for name in _ENTITY_REFERENCE.findall(text)
        if not name.startswith("镜头时长:")
    }
    if references - names:
        raise ValueError("Prompt 引用了未提供的资产，请使用当前目标已有的资产引用")
    if any(not entity.description.strip() for entity in entity_reference_names(text, entities)):
        raise ValueError("当前引用资产缺少完整描述，请先补齐已有资产设定")


def current_storyboard_structure(*, prompt: str | None, params: dict, sequence: int,
                                description: str | None, duration: float,
                                entities: Sequence[SceneEntity], strategy: StoryboardStrategyPrompt) -> SoraScenePromptConfig | None:
    try:
        candidate = SoraScenePromptConfig.model_validate({**params, 'sequence': sequence,
            'description': description or '', 'duration': f'{duration:g}s'})
    except ValueError:
        return None
    if prompt and format_storyboard_prompt(candidate, entities=entities, strategy=strategy).strip() != prompt.strip():
        return None
    return candidate


def prepare_storyboard_edit(
    *,
    edit: StoryboardPromptEdit,
    prompt: str | None,
    params: dict,
    sequence: int,
    description: str | None,
    duration: float,
    entities: Sequence[SceneEntity],
    strategy: StoryboardStrategyPrompt = CINEMATIC_STORYBOARD_STRATEGY,
) -> dict:
    if edit.legacy_prompt is not None:
        from prompts.creation_agent import without_prompt_definitions

        visual_prompt = normalize_storyboard_reference_text(without_prompt_definitions(edit.legacy_prompt), entities)
        validate_prompt_dependencies(visual_prompt, entities)
        numbers = [int(number) for number in _LOCAL_HEADING.findall(visual_prompt)]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("每个独立请求的小镜头编号必须从1开始连续排列")
        complete_prompt = normalize_storyboard_reference_text(render_preserved_tracks(visual_prompt, params), entities)
        referenced = entity_reference_names(complete_prompt, entities)
        return {
            "prompt": append_prompt_definitions(complete_prompt, referenced),
            # Preserve audio tracks/other metadata, but never revive stale visual fields.
            "prompt_params": {
                key: value for key, value in params.items()
                if key not in StoryboardVisualChanges.model_fields
            },
        }

    current = {
        **params,
        "sequence": sequence,
        "description": description or "",
        "duration": f"{duration:g}s",
    }
    if current_storyboard_structure(prompt=prompt, params=params, sequence=sequence, description=description,
                                   duration=duration, entities=entities, strategy=strategy) is None:
        raise ValueError("当前是空白或历史手工 Prompt，结构化参数不完整或不一致；请改用 legacy_prompt 提交完整纯文本，保留已有动作和声音")

    changes = edit.changes.model_dump(exclude_unset=True)
    candidate = SoraScenePromptConfig.model_validate({**current, **changes})
    candidate = SoraScenePromptConfig.model_validate({
        **candidate.model_dump(),
        **normalized_storyboard_reference_fields(candidate, entities),
    })
    # Existing dialogue is read-only and may legitimately mention a previous event.
    for name, value in candidate.model_dump(exclude={"dialogue", "narration"}).items():
        if name not in {"sequence", "duration"}:
            validate_prompt_dependencies(str(value), entities)
    rendered = format_storyboard_prompt(candidate, entities=entities, strategy=strategy)
    return {
        "prompt": rendered,
        "prompt_params": {
            **params,
            **candidate.model_dump(exclude={"sequence", "description", "duration"}),
        },
    }


def append_prompt_definitions(prompt: str, entities: Sequence[SceneEntity]) -> str:
    """Expand only definitions missing from a standalone legacy prompt."""
    from prompts.creation_agent import render_prompt_definitions

    missing = [entity for entity in entities if entity.description not in prompt]
    return render_prompt_definitions(prompt, missing)
