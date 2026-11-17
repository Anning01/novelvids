"""One Chinese rule source, bilingual display labels, and unchanged user facts."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from prompts.catalog import catalog, read_resource
from prompts.creation_agent import render_creation_instructions, render_summary_instructions
from test.visual_fields import trait_labels
from prompts.project_analysis import render_cover_prompt
from services.reference.generator import build_sora_compatible_prompt
from prompts.remake import render_remake_prompt
from prompts.skill_pack import read_skill
from schemas.creation_agent import StoryboardVisualChanges
from services.creation_agent.runtime import creation_agent, CreationAgentDeps
from services.extraction.extractor import AssetExtractionResult, Person
from utils.prompt_language import task_language

ROOT = Path(__file__).parents[2] / "prompts"


def english_traits(group=False):
    return "\n".join(f"{label}: stable visible detail" for label in trait_labels(group, "en"))


def test_locales_only_contain_display_and_historical_protocol_labels():
    for language in ("zh", "en"):
        assert {p.name for p in (ROOT / "locales" / language).iterdir()} == {
            "labels.json", "strategies.json",
        }
    for name in ("labels.json", "strategies.json"):
        assert catalog(name, "zh").keys() == catalog(name, "en").keys()
    assert not (ROOT / "legacy").exists()


def test_missing_or_traversing_locale_fails_explicitly():
    with pytest.raises(FileNotFoundError):
        catalog("nonexistent.json", "en")
    with pytest.raises(ValueError):
        read_resource(ROOT / "locales", "../zh/labels.json", "en")


@pytest.mark.parametrize("group", [False, True])
def test_both_historical_visual_field_languages_remain_readable(group):
    for language in ("zh", "en"):
        value = "\n".join(f"{label}: visible detail" for label in trait_labels(group, language))
        assert Person(name="Alex", label="group" if group else "person", base_traits=value).base_traits == value


def test_enum_aliases_do_not_change_stored_protocol_values():
    assert StoryboardVisualChanges(reference_only_types=["person", "item"]).reference_only_types == ["人物", "物品"]
    assert Person(name="Alex", label="person", base_traits=english_traits()).label == "人物"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_all_rule_renderers_use_the_same_skill_and_explicit_language(language):
    artifacts = [
        (render_cover_prompt(name="Signal", book_types=[], story_outline="Text", prompt_language=language), "image"),
        (render_creation_instructions(language=language), "editing"),
        (render_summary_instructions(language), "summary"),
        (render_remake_prompt("shots", language), "remake"),
    ]
    for rendered, skill in artifacts:
        assert read_skill(skill) in rendered
        assert "language=" + language in rendered
    from prompts.text_tasks import render_text_task, builtin_method
    for task in ('story', 'screenplay', 'assets', 'storyboard'):
        method = builtin_method(task)
        system, user = render_text_task(language=language, skill=method, context={'text': 'User input'})
        assert f'language={language}' in system
        assert json.loads(user)['creative_method']['instructions'] == method['instructions']


def test_saved_names_and_prompts_remain_verbatim():
    user_text = "  陈 Alex wears a {red} coat.  "
    for language in ("zh", "en"):
        assert build_sora_compatible_prompt({"base_traits": user_text}, language) == user_text




@pytest.mark.asyncio
@pytest.mark.parametrize("crud", [False, True])
async def test_assistant_keeps_one_tool_schema_in_both_languages(crud):
    observed = []
    def respond(messages, info):
        observed.append({t.name: t.parameters_json_schema for t in info.function_tools})
        assert read_skill("editing").strip() in info.instructions
        return ModelResponse(parts=[TextPart("Ready.")])
    for language in ("zh", "en"):
        token = task_language.set(language)
        try:
            await creation_agent.run("Help me plan.", deps=CreationAgentDeps(
                service=None, context={}, changes=SimpleNamespace(max_batch_size=8) if crud else None,
                tools_enabled=True), model=FunctionModel(respond))
        finally:
            task_language.reset(token)
    assert observed[0] == observed[1]
