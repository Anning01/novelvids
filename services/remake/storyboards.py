"""Use the workbench's structured storyboard contract for remade video segments."""

from math import isclose
from prompts.storyboard import referenced_entities

from schemas.agent_workflow import RemakeShot, StructuredSkillStoryboard
from schemas.scene import SceneEntity
from services.storyboard.strategies import storyboard_strategy_factory
from services.storyboard.validation import prepare_skill_storyboard, TIMELINE

# Model timeline labels commonly round source frame times to two decimals.
TIMELINE_ROUNDING_SECONDS = .005


def _align_timeline_end(line, duration):
    match = TIMELINE.match(line)
    if match and float(match[2]) > duration and isclose(float(match[2]), duration, abs_tol=TIMELINE_ROUNDING_SECONDS):
        return line[:match.start(2)] + f'{duration:g}' + line[match.end(2):]
    return line


def prepare_remake_prompt(raw, catalog, snapshot, language, *, strategy_key=None, duration_seconds=None):
    index = {item['id']: item for item in catalog}
    references = []
    for reference in raw['asset_refs']:
        if reference['asset_id'] not in index:
            raise ValueError('重制分镜引用了未登记资产')
        item = index[reference['asset_id']]
        references.append({'asset_id':item['id'],'asset_name':item['name'],'asset_type':item['type']})
    entities = [SceneEntity(name=item['name'], aliases=[item['id']], description=item['description'],
        asset_type={'character': '人物', 'scene': '场景', 'object': '物品'}[item['type']]) for item in catalog]
    content = {key:value for key,value in raw.items() if key in RemakeShot.model_fields}
    shot = RemakeShot.model_validate({**content, 'prompt': None, 'asset_refs':references,
                                    'sequence':raw.get('shot_index', raw.get('sequence'))})
    if duration_seconds is not None:
        updates = {field:[_align_timeline_end(line, duration_seconds) for line in getattr(shot,field)]
                   for field in ('actions','dialogue','narration')}
        segments = list(shot.segments)
        delta = duration_seconds - sum(segment.duration for segment in segments)
        if segments and abs(delta) <= TIMELINE_ROUNDING_SECONDS:
            last = segments[-1]
            segments[-1] = last.model_copy(update={'duration':last.duration + delta,
                'actions':[_align_timeline_end(line,last.duration + delta) for line in last.actions]})
        shot = shot.model_copy(update={**updates,'duration':f'{duration_seconds}s','segments':segments})
    prepared = prepare_skill_storyboard(StructuredSkillStoryboard(shots=[shot]), snapshot, language, entities,
        storyboard_strategy_factory.resolve(strategy_key).key).shots[0]
    used = {entity.name for entity in referenced_entities(prepared, entities)} | {reference['asset_name'] for reference in references}
    references = [{'asset_id':item['id'], 'asset_name':item['name'], 'asset_type':item['type']}
                  for item in catalog if item['name'] in used]
    return {**raw, **prepared.model_dump(mode='json'), 'asset_refs': references,
            'duration_seconds': float(prepared.duration.removesuffix('s'))}
