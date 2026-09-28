"""Complete prompt locales, output contracts, and provider-boundary regression tests."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart

from prompts.catalog import catalog, template
from prompts.creation_agent import (
    render_creation_instructions,
    render_summary_instructions,
    render_working_checkpoint,
)
from prompts.creation_standards import visual_contract, validate_person_visual_traits
from prompts.extraction import render_extraction_system, trait_labels
from prompts.project_analysis import render_analysis_messages, render_cover_prompt
from prompts.reference import render_default_asset_prompt
from prompts.remake import ASSET_SCHEMA, render_remake_prompt, render_remake_request
from prompts.schema import json_instruction, localized_schema
from prompts.storyboard import build_storyboard_messages
from prompts.storyboard_strategies import NARRATION_STORYBOARD_STRATEGY
from prompts.styles import (
    STYLE_KEYS,
    image_project_style_suffix,
    video_project_style_suffix,
)
from schemas.scene import SoraScenePromptConfig, Storyboard
from schemas.creation_agent import StoryboardVisualChanges, CreationReply
from services.extraction.extractor import AssetExtractor, AssetExtractionResult, Person
from services.project_analysis.handler import BookAnalysis
from services.creation_agent.runtime import creation_agent, CreationAgentDeps
from utils.prompt_language import task_language

HAN = re.compile(r"[\u3400-\u9fff]")
ROOT = Path(__file__).parents[2] / "prompts" / "templates"


def english_traits(group=False):
    return "\n".join(
        f"**{label}**: specific stable visual detail"
        for label in trait_labels(group, "en")
    )


def test_locale_resources_are_paired_and_english_resources_contain_no_chinese_prose():
    assert {p.name for p in (ROOT / "en").iterdir()} == {
        p.name for p in (ROOT / "zh").iterdir()
    }
    for resource in (ROOT / "en").iterdir():
        assert not HAN.search(resource.read_text()), resource.name
        if resource.suffix == ".json":
            assert (
                catalog(resource.name, "en").keys()
                == catalog(resource.name, "zh").keys()
            )


def test_missing_locale_resource_fails_instead_of_falling_back_to_chinese():
    with pytest.raises(FileNotFoundError):
        template("nonexistent.md", "en")
    with pytest.raises(ValueError):
        template("../zh/agent_crud.md", "en")


@pytest.mark.parametrize("group", [False, True])
def test_english_visual_fields_validate_and_legacy_fields_remain_accepted(group):
    english = english_traits(group)
    value = Person(
        name="Alex", label="group" if group else "person", base_traits=english
    )
    assert value.base_traits == english
    assert value.label == ("群像" if group else "人物")
    validate_person_visual_traits(
        english, "group_portrait" if group else "character_turnaround"
    )
    legacy = "\n".join(
        f"{label}: stable visual detail" for label in trait_labels(group, "zh")
    )
    assert (
        Person(name="Alex", label=value.label, base_traits=legacy).base_traits == legacy
    )
    with pytest.raises(ValidationError):
        Person(
            name="Alex",
            label=value.label,
            base_traits="\n".join(english.splitlines()[:-1]),
        )
    with pytest.raises(ValueError):
        validate_person_visual_traits(
            english.replace("specific stable visual detail", "unknown"),
            "group_portrait" if group else "character_turnaround",
        )


def test_english_enum_aliases_normalize_without_changing_persisted_contracts():
    assert StoryboardVisualChanges(
        reference_only_types=["person", "item"]
    ).reference_only_types == ["人物", "物品"]
    original = ASSET_SCHEMA.copy()
    translated = localized_schema(ASSET_SCHEMA, "en")
    assert translated["properties"]["characters"]["items"]["properties"]["label"][
        "enum"
    ] == ["person", "animal", "group"]
    assert ASSET_SCHEMA == original


def test_complete_english_instruction_paths_have_no_chinese_rules():
    messages = build_storyboard_messages(
        "Alex waits at the station.", [], "en", strategy=NARRATION_STORYBOARD_STRATEGY
    )
    artifacts = [
        render_extraction_system("en"),
        *[m["content"] for m in messages],
        *[
            m["content"]
            for m in render_analysis_messages(
                name="The Signal",
                chapter_count=2,
                material="Chapter 1: Arrival",
                prompt_language="en",
            )
        ],
        render_cover_prompt(
            name="The Signal",
            book_types=["Mystery"],
            story_outline="Alex finds a key.",
            prompt_language="en",
        ),
        render_creation_instructions(language="en", crud=False, turn_limited=True),
        render_creation_instructions(language="en", crud=True, turn_limited=True),
        render_summary_instructions("en"),
        render_working_checkpoint({"facts": []}, "en"),
        render_remake_request(
            render_remake_prompt("assets", "en"),
            context="",
            index=1,
            schema=ASSET_SCHEMA,
            include_segment_metadata=True,
            language="en",
        ),
        render_remake_prompt("shots", "en"),
    ]
    for kind in ["person", "scene", "item", "storyboard"]:
        artifacts.append(
            json.dumps(
                visual_contract(
                    kind,
                    language="en",
                    aspect_ratio="16:9",
                    strategy=NARRATION_STORYBOARD_STRATEGY,
                ),
                ensure_ascii=False,
            )
        )
    for model in [AssetExtractionResult, BookAnalysis, Storyboard, CreationReply]:
        artifacts.append(json_instruction(model.model_json_schema(), "en"))
    for key in STYLE_KEYS:
        artifacts.extend(
            [
                image_project_style_suffix(key, None, "en"),
                video_project_style_suffix(key, None, "en"),
            ]
        )
    for artifact in artifacts:
        assert not HAN.search(artifact), artifact


def test_user_names_and_custom_prompts_are_not_translated_or_reinterpreted():
    user_text = "陈 Alex wears a {red} coat."
    rendered = render_default_asset_prompt(
        asset_type="person", visual_traits=user_text, prompt_language="en"
    )
    assert user_text in rendered
    assert "Task: Create" in rendered
    assert (
        render_default_asset_prompt(
            asset_type="person", visual_traits=rendered, prompt_language="zh"
        )
        == rendered
    )
    assert video_project_style_suffix(None, user_text, "en").endswith(user_text)


@pytest.mark.asyncio
async def test_english_extraction_request_and_schema_reach_model_together():
    payload = {
        "persons": [
            {
                "name": "Alex Reed",
                "label": "person",
                "description": "Detective",
                "base_traits": english_traits(),
            }
        ],
        "scenes": [],
        "items": [],
    }
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload), refusal=None),
            )
        ],
        usage=None,
    )
    create = AsyncMock(return_value=completion)
    extractor = AssetExtractor(
        SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
        "test-model",
        prompt_language="en",
    )
    result = await extractor.extract(
        [
            {"role": "system", "content": render_extraction_system("en")},
            {"role": "user", "content": "Alex arrives. Alex returns."},
        ]
    )
    outgoing = create.call_args.kwargs["messages"]
    assert all(not HAN.search(message["content"]) for message in outgoing)
    assert result.persons[0].label == "人物"
    assert result.persons[0].base_traits == english_traits()


@pytest.mark.asyncio
@pytest.mark.parametrize("crud", [False, True])
async def test_assistant_tool_and_output_schemas_use_the_turn_language(crud):
    def respond(messages, info):
        assert not HAN.search(info.instructions)
        for definition in [*info.function_tools, *info.output_tools]:
            assert not HAN.search(definition.description or ""), definition.name
            assert not HAN.search(
                json.dumps(definition.parameters_json_schema, ensure_ascii=False)
            ), definition.name
        return ModelResponse(parts=[TextPart("Ready.")])

    token = task_language.set("en")
    try:
        await creation_agent.run(
            "Help me plan the story.",
            deps=CreationAgentDeps(
                service=None,
                context={},
                changes=SimpleNamespace(max_batch_size=8) if crud else None,
                tools_enabled=True,
            ),
            model=FunctionModel(respond),
        )
    finally:
        task_language.reset(token)
