import json
import shutil

import pytest

import prompts.skill_pack as pack


@pytest.fixture
def rules(tmp_path, monkeypatch):
    for filename in pack.FILES.values():
        (tmp_path / filename).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pack.ROOT / filename, tmp_path / filename)
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    return tmp_path


def test_new_runs_and_style_options_read_only_the_canonical_files(rules):
    from prompts.styles import get_style

    before = pack.snapshot_skills()
    (rules / "assets.anning.md").write_text("obsolete local instructions")
    (rules / "styles.anning.json").write_text('{"obsolete": {}}')
    assert pack.snapshot_skills() == before
    assert get_style("obsolete") is None
    (rules / pack.FILES["assets"]).write_text("Updated asset instructions")
    after = pack.snapshot_skills()
    assert after["revision"] != before["revision"]
    assert after["contents"]["assets"] == "Updated asset instructions"
    assert before["contents"]["assets"] != after["contents"]["assets"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_published_rules_supply_the_full_contract_to_new_tasks(rules, language):
    snapshot = pack.SkillSnapshot.model_validate(pack.snapshot_skills())
    assets = json.loads(snapshot.read("asset_contract"))[language]
    assert set(assets) == {"person", "group", "scene", "item"}
    assert len(assets["person"]["fields"]) == 14
    assert len(assets["group"]["fields"]) == 15
    rendered = pack.instructions(snapshot, language, "assets")
    assert all(spec["heading"] in rendered for spec in assets.values())
    storyboard = json.loads(snapshot.read("storyboard_contract"))
    assert len(storyboard["sections"]) == 8
    assert storyboard["speech_baseline"]["characters_per_second"] == 3.5


@pytest.mark.parametrize(("name", "content"), [
    ("assets", "  "), ("strategies", "[]"), ("strategies", "{broken"),
])
def test_invalid_rule_reports_its_name(rules, name, content):
    (rules / pack.FILES[name]).write_text(content)
    with pytest.raises(ValueError, match=f"Invalid {name}"):
        pack.read_skill(name)
