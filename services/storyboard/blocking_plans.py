"""Ask the selected text model to stage a shot when its storyboard lacks a diagram."""
from schemas.scene import BlockingMap, SceneLayout
from services.storyboard.validation import validate_blocking_map
from utils.messages import localized_message


class ShotPlacement(BlockingMap):
    # Known fixed geometry is attached by the server; the model supplies the entire overlay.
    layout: None = None


class NewLocationPlacement(BlockingMap):
    layout: SceneLayout


def ending_state(shot):
    return {'spatial_relationships': shot.spatial_relationships, 'visual_prose': shot.visual_prose,
            'actions': shot.actions, 'transition': shot.transition,
            'map': shot.blocking_map.model_dump() if shot.blocking_map else None}


async def place_shot(execution, shot, entities, layouts, previous, scene_text, segment):
    visible = set(shot.visible_asset_names or [])
    location = next((e.name for e in entities if e.asset_type == "场景" and e.name in visible), None)
    layout = next((item for item in layouts.values() if item["name"] == location), None)

    async def check(plan):
        if plan.layout is not None and location and plan.layout.name != location:
            raise ValueError(localized_message("请沿用当前场景的登记名"))
        combined = plan.model_copy(update={'layout': SceneLayout.model_validate(layout)}) if layout else plan
        checked = BlockingMap.model_validate(combined.model_dump())
        if not checked.layout or any(not cam.frame or not cam.framing for cam in checked.cameras):
            raise ValueError(localized_message("空间定位图须包含场地、机位、景别和取景范围"))
        if checked.layout.id in layouts and checked.layout.model_dump() != layouts[checked.layout.id]:
            raise ValueError(localized_message("同一场景形态的底图发生变化，请复用已确认的底图"))
        validate_blocking_map(shot.model_copy(update={'blocking_map': checked}), execution.snapshot, entities, required=True)
        return checked

    if shot.blocking_map and shot.blocking_map.layout:
        try:
            plan = await check(shot.blocking_map)
        except ValueError:
            plan = None
    else:
        plan = None
    if plan is None:
        facts = {'segment': segment, 'screenplay': scene_text, 'shot': shot.model_dump(exclude={'prompt', 'blocking_map'}),
                 'location_name': location, 'fixed_layout': layout, 'previous_shot': previous}
        generated = await execution.generate('structured', facts, ShotPlacement if layout else NewLocationPlacement,
            additional_instructions=execution.snapshot.read('blocking_guide'), output_validator=check)
        plan = await check(generated)
    layouts[plan.layout.id] = plan.layout.model_dump()
    return shot.model_copy(update={'blocking_map': plan})


async def fill_saved_shots(params):
    from models.chapter import Chapter
    from models.scene import Scene
    from schemas.scene import SceneEntity, SoraScenePromptConfig
    from services.creation_agent.skill_execution import current_execution
    from services.creation_objects import project_write
    from services.storyboard.chunking import screenplay_sections
    from utils.enums import AssetTypeEnum

    execution = current_execution.get()
    chapter = await Chapter.get(id=params['chapter_id'], novel_id=params['novel_id'])
    sections = dict(screenplay_sections(chapter.production_text))
    scenes = await Scene.filter(chapter=chapter).order_by('sequence').prefetch_related('assets')
    layouts, previous, ids = {}, None, []
    previous_scene = None
    for scene in scenes:
        await execution.before_request()
        data = scene.prompt_params or {}
        structure = {key: value for key, value in data.items() if key in SoraScenePromptConfig.model_fields}
        shot = SoraScenePromptConfig.model_validate({**structure, 'sequence':scene.sequence,
            'duration':f'{scene.duration:g}s', 'description':scene.description, 'prompt':scene.prompt})
        number = data.get('source_scene_number')
        continuation = previous is not None and (
            number == previous_scene if number else not previous_scene and shot.duration_split_part is not None)
        previous_scene = number
        if not continuation:
            previous = ending_state(shot)
            continue
        entities = [SceneEntity(name=a.canonical_name, asset_type=AssetTypeEnum(a.asset_type).nickname,
            asset_id=a.id, aliases=a.aliases or [], description=a.description or '') for a in scene.assets]
        source = sections.get(data.get('source_scene_number'), chapter.production_text)
        placed = await place_shot(execution, shot, entities, layouts, previous, source, f'saved-shot:{scene.id}')
        plan = placed.blocking_map.model_dump(exclude_none=True)
        previous = ending_state(placed)
        if data.get('blocking_map') != plan:
            async with project_write(chapter.novel_id):
                current = await Scene.get(id=scene.id)
                if current.prompt != scene.prompt or current.prompt_params != data or current.sequence != scene.sequence:
                    raise ValueError(localized_message('分镜已更新，请重新生成空间定位图'))
                current.prompt_params = {**data, 'blocking_map':plan}
                await current.save(update_fields=['prompt_params', 'updated_at'])
        ids.append(scene.id)
    return {'scene_ids':ids, 'blocking_maps':len(ids)}
