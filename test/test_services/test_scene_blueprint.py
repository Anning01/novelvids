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
    result = SimpleNamespace(shots=[SimpleNamespace(blocking_map=plan, duration_split_part=2)])
    with pytest.raises(ValueError, match="复用"):
        prepare_skill_storyboard(result, SkillSnapshot.model_validate(snapshot_skills()), "zh", [], "cinematic",
                                 scene_layouts={"hall-a": LAYOUT})


@pytest.mark.asyncio
async def test_model_supplies_distinct_shot_positions_and_receives_previous_camera():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from schemas.scene import SceneEntity
    from services.storyboard.blocking_plans import place_shot, NewLocationPlacement, ShotPlacement
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from test.test_services.test_prompt_language import _shot

    first = NewLocationPlacement.model_validate({**SHOT,'layout':LAYOUT})
    reverse = ShotPlacement.model_validate({**SHOT,'cameras':[{**SHOT['cameras'][0], 'x':65, 'framing':'反打近景'}]})
    execution = SimpleNamespace(snapshot=SkillSnapshot.model_validate(snapshot_skills()),
        generate=AsyncMock(side_effect=[first, reverse]))
    layouts = {}
    shot = _shot()
    shot.visible_asset_names = ['展厅','访客']
    entities = [SceneEntity(name='展厅', asset_type='场景', aliases=[],description='展厅'),
                SceneEntity(name='访客', asset_type='人物',aliases=[],description='访客')]
    wide = await place_shot(execution, shot, entities, layouts, None, '剧本', 'one')
    state = {'map':wide.blocking_map.model_dump(), 'actions':wide.actions, 'transition':wide.transition}
    close = await place_shot(execution, shot, entities, layouts, state, '剧本', 'two')
    calls = execution.generate.await_args_list
    assert [c.args[2] for c in calls] == [NewLocationPlacement, ShotPlacement]
    assert calls[1].args[1]['previous_shot'] == state
    assert wide.blocking_map.layout == close.blocking_map.layout
    assert wide.blocking_map.cameras != close.blocking_map.cameras
    assert draw(wide.blocking_map.model_dump(exclude_none=True)) != draw(close.blocking_map.model_dump(exclude_none=True))


@pytest.mark.asyncio
async def test_seven_parts_have_six_continuity_maps_and_next_scene_starts_fresh():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from schemas.agent_workflow import StructuredSkillStoryboard
    from schemas.scene import SceneEntity
    from services.creation_agent.skill_execution import current_execution
    from services.storyboard.generator import generate_storyboard
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from test.test_services.test_prompt_language import _shot

    evidence = []
    async def generate(skill, facts, output_type, **options):
        if skill == 'storyboard':
            count = 7 if facts['source_scene_number'] == '1-2' else 1
            shots = []
            for index in range(count):
                shot = _shot()
                shot.visible_asset_names = ['展厅', '访客']
                shot.transition = f'第{index+1}段走位落点'
                shots.append(shot.model_dump(exclude={'prompt'}))
            return StructuredSkillStoryboard.model_validate({'shots':shots})
        evidence.append(facts['previous_shot'])
        data = {**SHOT, **({} if facts['fixed_layout'] else {'layout':LAYOUT})}
        plan = output_type.model_validate(data)
        await options['output_validator'](plan)
        return plan
    entities = [SceneEntity(name='展厅', asset_type='场景', aliases=[], description='展厅'),
                SceneEntity(name='访客', asset_type='人物', aliases=[], description='访客')]
    execution = SimpleNamespace(snapshot=SkillSnapshot.model_validate(snapshot_skills()),
        params={'assistant_model_config_id':1}, generate=generate)
    token = current_execution.set(execution)
    try:
        result, _ = await generate_storyboard(None, '1-2 展厅 内 日\n两人相向走近。\n1-3 展厅 内 夜\n散场。', entities, 'mock')
    finally:
        current_execution.reset(token)
    assert [s.duration_split_part for s in result.shots] == [None, 2, 3, 4, 5, 6, 7, None]
    assert [bool(s.blocking_map) for s in result.shots] == [False, *([True]*6), False]
    assert [s['transition'] for s in evidence] == [f'第{i}段走位落点' for i in range(1,7)]
    assert evidence[0]['map'] is None and evidence[0]['spatial_relationships']
    assert all(s['map'] for s in evidence[1:])
