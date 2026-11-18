"""Deterministic conversion and rendering of an already constrained storyboard response."""

from difflib import SequenceMatcher

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


def _resembles_scene_name(written, registered):
    """One typo or one omitted interior qualifier, corroborated separately by the environment."""
    if min(len(written), len(registered)) < 3 or '#' in written or '#' in registered:
        return False
    changes = [op for op in SequenceMatcher(None, written, registered, autojunk=False).get_opcodes()
               if op[0] != 'equal']
    if len(changes) != 1:
        return False
    kind, start, end, left, right = changes[0]
    return max(end - start, right - left) == 1 or (kind == 'insert' and 0 < start < len(written))


def _resolve_scene_names(names, unknown, environment, entities):
    corrections = {}
    for name in unknown:
        matches = [entity for entity in entities if name in entity.aliases]
        if not matches:
            matches = [entity for entity in entities if _resembles_scene_name(name, entity.name)]
            if len(matches) != 1 or matches[0].name != environment:
                continue
        if len(matches) == 1 and matches[0].asset_type == '场景' and '#' not in name:
            corrections[name] = matches[0].name
    unresolved = unknown - corrections.keys()
    if unresolved:
        raise ValueError(localized_message('出镜名单含未登记的资产或形态：{p0}', p0='、'.join(sorted(unresolved))))
    # Temporary aliases also normalize markers in this shot without changing the asset catalog.
    aliases = {}
    for name, canonical in corrections.items():
        aliases.setdefault(canonical, []).append(name)
    shot_entities = [entity.model_copy(update={'aliases': [*entity.aliases, *aliases[entity.name]]})
                     if entity.name in aliases else entity for entity in entities]
    return list(dict.fromkeys(corrections.get(name, name) for name in names)), shot_entities


def storyboard_result(payload, language, entities, strategy):
    known = {entity.name for entity in entities}
    shots = []
    for number, raw in enumerate(payload['shots'], 1):
        # Asset ownership is a persistence boundary, not a formatting or editorial check.
        names = raw['visible_asset_names']
        shot_entities = entities
        if unknown := set(names) - known:
            names, shot_entities = _resolve_scene_names(names, unknown, raw['environment'], entities)
        shot = SkillShot.model_construct(**{**raw, 'visible_asset_names': names, 'sequence': number, 'duration': f'{raw["duration"]:g}s',
            'actions': [render_timed_action(value) for value in raw['actions']],
            'narration': [render_timed_speech(value, language) for value in raw['narration']],
            'dialogue': [render_timed_speech(value, language) for value in raw['dialogue']],
            'segments': [ScenePromptSegment.model_construct(**value) for value in raw['segments']],
            'blocking_map': blocking_map(raw['blocking_map']), 'reference_only_types': ['人物', '场景', '物品']})
        shot = shot.model_copy(update=normalized_storyboard_reference_fields(shot, shot_entities))
        shot.prompt = format_storyboard_prompt(shot, language, entities=shot_entities, strategy=strategy)
        shots.append(shot)
    return SkillStoryboard.model_construct(shots=shots)
