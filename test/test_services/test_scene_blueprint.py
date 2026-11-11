import json
import subprocess
import sys
from pathlib import Path
from xml.etree.ElementTree import fromstring, tostring

import pytest
from schemas.scene import BlockingMap
from prompts.skills.scripts.draw_blocking import draw
from services.storyboard.blocking_reference import blocking_source, standalone_svg

LAYOUT = {"id": "hall-a", "name": "展厅", "orientation": "北在上", "features": [
    {"name": "展台", "kind": "footprint", "points": [{"x": 20,"y": 20},{"x": 20,"y": 60},{"x": 40,"y": 40}]}]}
SHOT = {"orientation": "北在上", "assets": [{"name": "访客", "x": 28, "y": 40, "kind": "person", "heading": 90}],
        "cameras": [{"x": 30, "y": 60, "target": "访客", "frame": [{"x": 17,"y": 30},{"x": 40,"y": 30}],
                     "framing":"平视中景","beat":"访客趋近展台。"}]}


def test_portable_shared_base_has_identical_geometry_and_labels(tmp_path):
    script = Path("prompts/skills/scripts/draw_blocking.py").resolve()
    (tmp_path/"layout.json").write_text(json.dumps(LAYOUT))
    (tmp_path/"shot.json").write_text(json.dumps(SHOT))
    def render(*args):
        subprocess.run([sys.executable,"-I","-S",script,"shot.json","shot.svg","--layout","layout.json",*args],
                       cwd=tmp_path,check=True)
        return fromstring((tmp_path/"shot.svg").read_bytes())
    base, shot = render("--base-only"), render()
    assert tostring(base.find(".//*[@id='scene-layout']")) == tostring(shot.find(".//*[@id='scene-layout']"))
    assert not list(base.find(".//*[@id='shot-overlay']"))
    assert shot.find(".//*[@id='shot-overlay']/{*}polygon") is not None
    plan = BlockingMap.model_validate({**SHOT,"layout":LAYOUT})
    assert standalone_svg(draw(plan.model_dump(exclude_none=True)).encode())
    assert blocking_source(9, {}, {"blocking_map":plan.model_dump(),"segments":[]}) == "/api/scene/9/blocking-map.svg"
    with pytest.raises(ValueError, match="different layout"):
        draw(plan.model_dump(), {**LAYOUT,"id":"another"})


@pytest.mark.asyncio
async def test_next_episode_reads_only_its_location_layout():
    from models.asset import Asset
    from models.chapter import Chapter
    from models.novel import Novel
    from models.scene import Scene
    from schemas.scene import SceneEntity
    from services.storyboard.appearances import existing_scene_layouts

    novel = await Novel.create(name="场地图")
    first = await Chapter.create(novel=novel, number=1, name="一", content="开场")
    second = await Chapter.create(novel=novel, number=2, name="二", content="重返")
    asset = await Asset.create(novel=novel, canonical_name=LAYOUT["name"], asset_type=2)
    scene = await Scene.create(chapter=first, sequence=1, prompt_params={"blocking_map": {**SHOT, "layout": LAYOUT}})
    await scene.assets.add(asset)
    location = SceneEntity(name=asset.canonical_name, description="室内", aliases=[], asset_type="场景", asset_id=asset.id)
    assert await existing_scene_layouts(second, [location]) == {"hall-a": LAYOUT}
    assert await existing_scene_layouts(second, [location.model_copy(update={"name": "另一形态"})]) == {}


@pytest.mark.parametrize("change", [{"id":"another-id"}, {"features": LAYOUT["features"] * 2}])
def test_generation_cannot_redraw_same_location(change):
    from types import SimpleNamespace
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from services.storyboard.validation import prepare_skill_storyboard
    plan = BlockingMap.model_validate({**SHOT,"layout": {**LAYOUT, **change}})
    result = SimpleNamespace(shots=[SimpleNamespace(blocking_map=plan)])
    with pytest.raises(ValueError, match="复用"):
        prepare_skill_storyboard(result, SkillSnapshot.model_validate(snapshot_skills()), "zh", [], "cinematic",
                                 scene_layouts={"hall-a": LAYOUT})
