"""The single skill pack is the only source of creative instructions."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart

from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills
from prompts.styles import list_styles
from services.creation_agent.context_budget import ContextBudget
from services.creation_agent.skill_execution import SkillExecution, current_execution
from services.project_analysis.handler import _build_analysis_material
from services.remake.pipeline import RemakeDecompositionPipeline


def test_old_creative_templates_are_removed_and_only_ui_locales_remain():
    root = Path(__file__).parents[2] / "prompts"
    assert not (root / "legacy").exists()
    assert not (root / "templates").exists()
    assert set((root / "skills").glob("en/*")) == set()
    for language in ("zh", "en"):
        assert {p.name for p in (root / "locales" / language).iterdir()} == {"labels.json", "strategies.json"}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_scene_image_rules_require_cinematic_panels_without_design_sheet_labels(language):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    rendered = instructions(snapshot, language, "image")
    assert f"language={language}" in rendered
    for rule in ("2×2等大画面", "画面铺满到边缘", "不要留白", "标题栏", "不画文字", "视角名称", "正交投影", "室内与室外", "写进保存的完整提示词"):
        assert rule in rendered
    assert snapshot.read("image") in rendered


@pytest.mark.asyncio
async def test_scene_editing_contract_uses_the_same_frozen_image_rules(skill_execution):
    from models.novel import Novel
    from services.creation_agent.prompt_standards import CreationPromptStandards

    project = await Novel.create(name="Office reference")
    contract = await CreationPromptStandards(project.id).contract("scene")
    assert contract["language"] == "en"
    assert contract["revision"] == skill_execution.snapshot.revision
    assert contract["writing_rules"] == skill_execution.snapshot.read("image") + "\n" + skill_execution.snapshot.read("assets")


@pytest.mark.parametrize("language", ["zh", "en"])
def test_image_rules_keep_style_and_reference_roles_separate_from_character_layout(language):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    rendered = instructions(snapshot, language, "image")
    assert f"language={language}" in rendered
    for rule in ("单人、群像", "对应 key 的完整渲染要求", "自定义风格优先", "不能只写风格名称", "风格定义画法", "风格参考不复制其中的人脸", "多人同框需要明确成员"):
        assert rule in rendered


@pytest.mark.parametrize("language", ["zh", "en"])
def test_asset_rules_keep_full_chapter_cast_flashbacks_and_identities(language):
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    rendered = instructions(snapshot, language, "assets")
    assert f"language={language}" in rendered
    for rule in ("包含已登记且本章出场的资产", "不能只返回新对象或变更项", "真正演出的回忆", "已去世不等于没有出场", "不能单凭", "不把师徒、前后任或同名者的资料互换", "不把当前哭泣、跪拜、坐化"):
        assert rule in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["character_turnaround", "group_portrait"])
async def test_single_and_group_editing_contracts_share_project_style(skill_execution, layout):
    from models.novel import Novel
    from services.creation_agent.prompt_standards import CreationPromptStandards

    project = await Novel.create(name="Modern engineers", style_key="chinese-3d")
    contract = await CreationPromptStandards(project.id).contract("person", layout)
    assert contract["reference_layout"] == layout
    assert contract["project_style_key"] == "chinese-3d"
    assert contract["styles"] == skill_execution.snapshot.read("styles")
    assert contract["writing_rules"] == skill_execution.snapshot.read("image") + "\n" + skill_execution.snapshot.read("assets")


@pytest.fixture
def skill_execution():
    execution = SkillExecution(
        {"prompt_language": "en", "skill_snapshot": snapshot_skills()},
        None,
        AsyncMock(),
    )
    token = current_execution.set(execution)
    try:
        yield execution
    finally:
        current_execution.reset(token)


def test_style_options_follow_the_single_skill_resource(tmp_path, monkeypatch):
    import prompts.skill_pack as pack
    from services.project_config import validate_project_config

    styles = {"new-style": {"label": "新风格", "image": "规则", "video": "规则"}}
    (tmp_path / "styles.json").write_text(json.dumps(styles))
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    assert list_styles() == [{"key": "new-style", "label": "新风格"}]
    assert validate_project_config({"style_key": "new-style"}) == {"style_key": "new-style"}


def test_skill_checkpoint_contains_only_evidence(skill_execution):
    budget = ContextBudget(SimpleNamespace())
    budget._remember_evidence(
        [ModelRequest(parts=[UserPromptPart("Keep Alex Chen's name.")])], None
    )
    payload = json.loads(budget.recovery_part.content)
    assert set(payload) == {"working_checkpoint"}
    assert payload["working_checkpoint"]["requests"] == ["Keep Alex Chen's name."]


@pytest.mark.parametrize("with_chapters", [False, True])
def test_skill_manuscript_sampling_uses_facts_instead_of_templates(
    with_chapters
):
    novel = SimpleNamespace(content="Original manuscript. " * 4000)
    chapters = [SimpleNamespace(number=1, name="Chapter 1: Arrival", content=novel.content)]
    result = _build_analysis_material(
        novel, chapters if with_chapters else [], "en"
    )
    payload = json.loads(result)
    assert "Original manuscript." in str(payload)
    if with_chapters:
        assert payload["chapter_number"] == 1
        assert payload["title"] == chapters[0].name
    else:
        assert set(payload) == {"head", "tail"}


@pytest.mark.asyncio
async def test_skill_remake_does_not_build_unused_legacy_prompts(
    skill_execution, tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("New remake prepared a legacy bilingual prompt")

    monkeypatch.setattr("services.remake.pipeline.render_remake_prompt", forbidden)
    monkeypatch.setattr("services.remake.pipeline.render_remake_catalog", forbidden)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    gateway = SimpleNamespace(
        analyze_one=AsyncMock(return_value={"characters": [], "scenes": [], "objects": []}),
        analyze_many=AsyncMock(return_value=[{
            "prompt": "The saved complete shot.", "asset_refs": [], "confidence": 1,
        }]),
        usage={}, timings=[],
    )
    pipeline = RemakeDecompositionPipeline(
        scene_detector=SimpleNamespace(split=lambda *args: [source]),
        gateway_factory=lambda config: gateway,
        prepare_video=lambda path, *args, **kwargs: path,
        probe_duration=lambda path: 4,
    )
    result = await pipeline.run(
        source_path=source,
        model_config=SimpleNamespace(id=1, model="vision"),
        work_dir=tmp_path / "work",
    )
    assert gateway.analyze_one.call_args.kwargs["prompt"] == ""
    assert gateway.analyze_many.call_args.kwargs["prompt"] == ""
    assert json.loads(gateway.analyze_many.call_args.kwargs["context_builder"](1)) == {
        "characters": [], "scenes": [], "objects": [],
    }
    assert result.prompt_document["prompts"][0]["prompt"] == "The saved complete shot."
