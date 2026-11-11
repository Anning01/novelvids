import json
import re
from pathlib import Path

import pytest

from prompts.skill_pack import FILES, ROOT, SkillSnapshot, instructions, snapshot_skills
from scripts.export_skill import LINK, entrypoints, export_skill


STAGES = ("story", "screenplay", "assets", "image", "storyboard", "video", "remake")


def test_only_professional_stages_are_publishable(tmp_path):
    assert set(entrypoints()) == {f"novelvids-{stage}" for stage in STAGES}
    for retired in ("novelvids-planning", "novelvids-editing"):
        with pytest.raises(ValueError, match="Unknown skill"):
            export_skill(retired, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", STAGES)
def test_stage_exports_without_application_files(tmp_path, name):
    package = export_skill(f"novelvids-{name}", tmp_path)
    source = ROOT / package.name / "SKILL.md"
    entry = (package / "SKILL.md").read_text()
    assert f"name: {package.name}\n" in entry
    targets = [package / match[2] for match in LINK.finditer(entry)]
    assert targets and set(targets) == {p for p in package.rglob("*") if p.is_file() and p.name not in {"SKILL.md", "LICENSE"}}
    assert (package / "LICENSE").read_bytes() == (ROOT.parents[1] / "LICENSE").read_bytes()
    for match, target in zip(LINK.finditer(source.read_text()), targets, strict=True):
        assert target.resolve().is_relative_to(package)
        assert target.read_bytes() == (source.parent / match[2]).read_bytes()
    assert not list(package.rglob("*.py"))
    assert list(tmp_path.iterdir()) == [package]


def test_export_keeps_unrelated_and_preexisting_skills(tmp_path):
    installed = export_skill("novelvids-storyboard", tmp_path)
    entry = installed / "SKILL.md"
    entry.write_text("Local edits")
    with pytest.raises(FileExistsError):
        export_skill("novelvids-storyboard", tmp_path)
    with pytest.raises(ValueError):
        export_skill("../runtime", tmp_path)
    assert entry.read_text() == "Local edits"


def test_saved_rules_come_from_the_same_files_as_the_standalone_package(tmp_path):
    package = export_skill("novelvids-storyboard", tmp_path)
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    for key in ("storyboard", "storyboard_contract", "styles", "strategies"):
        assert snapshot.read(key) == (package / "references" / Path(FILES[key]).name).read_text()
    templates = json.loads(snapshot.read("storyboard_templates"))
    templates["contract"] = "FROZEN CONTRACT LABEL"
    snapshot.contents["storyboard_templates"] = json.dumps(templates)
    assert "FROZEN CONTRACT LABEL" in instructions(snapshot, "en", "storyboard")
    # A pre-split job has its original rules and no separate renderer template file.
    del snapshot.contents["storyboard_templates"]
    assert json.loads(snapshot.read("storyboard_contract"))["sections"]
    assert "FROZEN CONTRACT LABEL" not in instructions(snapshot, "en", "storyboard")


def test_task_uses_frozen_repair_rules_and_restores_caller_context():
    from prompts.extraction import targeted_cast_instructions
    from prompts.skill_pack import use_skill_snapshot

    original = targeted_cast_instructions("en")
    saved = snapshot_skills()
    resource = json.loads(saved["contents"]["asset_templates"])
    resource["targeted_cast_instructions"]["en"] = "Frozen task instruction"
    saved["contents"]["asset_templates"] = json.dumps(resource)
    with pytest.raises(RuntimeError), use_skill_snapshot(saved):
        assert targeted_cast_instructions("en") == "Frozen task instruction"
        with use_skill_snapshot(None):
            assert targeted_cast_instructions("en") == original
        assert snapshot_skills()["contents"] == saved["contents"]
        raise RuntimeError("interrupted")
    assert targeted_cast_instructions("en") == original


@pytest.mark.parametrize("language", ["zh", "en"])
def test_screenplay_export_and_workbench_share_scene_and_voice_notation(tmp_path, language):
    package = export_skill("novelvids-screenplay", tmp_path)
    rules = (package / "references/screenplay.md").read_text()
    prompt = instructions(SkillSnapshot.model_validate(snapshot_skills()), language, "screenplay")
    assert rules in prompt and f"language={language}" in prompt
    for marker in ("出场：", "仅声音：", "关键道具：", "△", "（OS）", "（画外）", "旁白：", "【音效】", "【屏显】"):
        assert marker in rules

    example = rules.split("```text\n", 1)[1].split("```", 1)[0]
    voices = [line for line in example.splitlines() if "：" in line and not line.startswith(
        ("出场：", "仅声音：", "关键道具：", "△", "【音效】", "【屏显】", "旁白：")
    )]
    assert all(re.fullmatch(r"[^：（]+(?:（[^）]+）)?：.+", line) for line in voices)
    assert all("（开口" not in line for line in voices)
    assert any(re.fullmatch(r"[^：（]+：.+", line) for line in voices)
    assert any("（压低声音）：" in line for line in voices)
    assert any("（OS）：" in line for line in voices)
    assert any("（画外）：" in line for line in voices)

    headers, action = example.split("\n\n", 1)
    assert "出场：阿岚、船工、驮马" in headers and "驮马" in action
    assert "仅声音：守闸人" in headers
    assert "关键道具：铜钱" in headers and "两枚铜钱" in action


@pytest.mark.parametrize("language,source", [("zh", "导演剧本"), ("en", "director's screenplay")])
def test_asset_inventory_and_export_use_screenplay_as_the_presence_source(tmp_path, language, source):
    from prompts.extraction import render_cast_instructions, targeted_cast_instructions

    package = export_skill("novelvids-assets", tmp_path)
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    prompt = instructions(snapshot, language, "assets")
    for key in ("assets", "asset_lifecycle", "image"):
        assert (package / "references" / Path(FILES[key]).name).read_text() == snapshot.read(key)
        assert snapshot.read(key) in prompt
    assert source in render_cast_instructions(language)
    assert source in targeted_cast_instructions(language)
    for handoff in ("导演剧本", "风格确认", "资产连续性.md", "参考图"):
        assert handoff in prompt


def test_standalone_storyboard_offers_a_baseline_and_performance_guidance(tmp_path):
    pkg = export_skill("novelvids-storyboard", tmp_path)
    rules = (pkg / "references/speech_pacing.md").read_text()
    contract = json.loads((pkg / "references/storyboard_contract.json").read_text())
    assert contract["speech_baseline"] == {"characters_per_second": 3.5, "words_per_second": 2.1}
    assert "speech_timing" not in contract
    assert "争吵" in rules and "六字诀" in rules
    assert not (pkg / "scripts/check_speech.py").exists()


@pytest.mark.parametrize("stage", ["storyboard", "video", "remake"])
def test_video_stages_share_one_script_driven_presentation_rule(tmp_path, stage):
    package = export_skill(f"novelvids-{stage}", tmp_path)
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    rule = (package / "references/video_presentation.md").read_text()
    assert rule == snapshot.read("video_presentation")
    for language in ("zh", "en"):
        rendered = instructions(snapshot, language, stage, output_kind="professional_video_prompt_material")
        assert rule in rendered
        assert all(element in rule for element in ("字幕", "水印", "LOGO", "背景音乐"))
        assert "无字幕、无水印" not in rendered and "不得添加 BGM" not in rendered
