import pytest

from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills


@pytest.mark.parametrize("language", ["zh", "en"])
def test_asset_extraction_includes_image_contract_without_tool_reads(language):
    raw = snapshot_skills()
    raw["contents"]["image"] = "Frozen image rules for this run"
    snapshot = SkillSnapshot.model_validate(raw)
    rendered = instructions(snapshot, language, "assets")
    assert snapshot.read("image") in rendered
    assert snapshot.read("assets") in rendered
    assert f"language={language}" in rendered
    assert "Frozen image rules" not in instructions(snapshot, language, "story")


def test_asset_design_rules_cover_specific_designs_instead_of_plot_summaries():
    rules = SkillSnapshot.model_validate(snapshot_skills()).read("assets")
    for requirement in (
        "眉眼", "鼻梁", "嘴唇", "头身比", "上装", "下装", "鞋履",
        "人数规模", "个体差异", "近景、中景、远景", "空间拓扑",
        "结构部件", "磨损", "普通校服", "逐项自检",
    ):
        assert requirement in rules
