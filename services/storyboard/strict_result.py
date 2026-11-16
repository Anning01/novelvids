"""Deterministic conversion and rendering of an already constrained storyboard response."""

from prompts.storyboard import format_storyboard_prompt, normalized_storyboard_reference_fields
from prompts.text_tasks import render_timed_action, render_timed_speech
from schemas.scene import PlanPoint, PlanAsset, PlanFeature, SceneLayout, PlanCamera, BlockingMap, ScenePromptSegment
from schemas.agent_workflow import SkillShot, SkillStoryboard
from utils.messages import localized_message


def blocking_map(data):
    if data is None:
        return None
    def point(value):
        return PlanPoint.model_construct(**value)
    layout = data['layout']
    if layout is not None:
        layout = SceneLayout.model_construct(**{**layout, 'features': [
            PlanFeature.model_construct(**{**feature, 'points': [point(p) for p in feature['points']]})
            for feature in layout['features']]})
    assets = [PlanAsset.model_construct(**{**asset, 'end': point(asset['end']) if asset['end'] else None,
        'route': [point(p) for p in asset['route']]}) for asset in data['assets']]
    cameras = [PlanCamera.model_construct(**{**camera,
        'frame': (point(camera['frame']['left']), point(camera['frame']['right'])) if camera['frame'] else None})
        for camera in data['cameras']]
    return BlockingMap.model_construct(**{**data, 'layout': layout, 'assets': assets, 'cameras': cameras,
        'axis': (data['axis']['first'], data['axis']['second']) if data['axis'] else None})


def storyboard_result(payload, language, entities, strategy):
    known = {entity.name for entity in entities}
    shots = []
    for number, raw in enumerate(payload['shots'], 1):
        # Asset ownership is a persistence boundary, not a formatting or editorial check.
        if set(raw['visible_asset_names']) - known:
            raise ValueError(localized_message('出镜名单含未登记的资产或形态：{p0}',
                p0='、'.join(sorted(set(raw['visible_asset_names']) - known))))
        shot = SkillShot.model_construct(**{**raw, 'sequence': number, 'duration': f'{raw["duration"]:g}s',
            'actions': [render_timed_action(value) for value in raw['actions']],
            'narration': [render_timed_speech(value, language) for value in raw['narration']],
            'dialogue': [render_timed_speech(value, language) for value in raw['dialogue']],
            'segments': [ScenePromptSegment.model_construct(**value) for value in raw['segments']],
            'blocking_map': blocking_map(raw['blocking_map']), 'reference_only_types': ['人物', '场景', '物品']})
        shot = shot.model_copy(update=normalized_storyboard_reference_fields(shot, entities))
        shot.prompt = format_storyboard_prompt(shot, language, entities=entities, strategy=strategy)
        shots.append(shot)
    return SkillStoryboard.model_construct(shots=shots)
