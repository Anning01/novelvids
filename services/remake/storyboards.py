"""Use the workbench's structured storyboard contract for remade video segments."""

from prompts.storyboard import referenced_entities

from schemas.agent_workflow import RemakeShot
from schemas.scene import SceneEntity
from services.storyboard.strategies import storyboard_strategy_factory


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
    from prompts.storyboard import format_storyboard_prompt, normalized_storyboard_reference_fields
    from prompts.storyboard_strategies import StoryboardStrategyPrompt
    import json
    strategy_key = storyboard_strategy_factory.resolve(strategy_key).key
    resource = json.loads(snapshot.read("strategies"))[strategy_key]
    strategy = StoryboardStrategyPrompt(key=strategy_key, name=strategy_key, description="",
        prohibitions=resource["restrictions"], generation_rules=resource["rules"])
    prepared = shot.model_copy(update=normalized_storyboard_reference_fields(shot, entities))
    prompt = format_storyboard_prompt(prepared, language, entities=entities, strategy=strategy, localize_strategy=False)
    used = {entity.name for entity in referenced_entities(prepared, entities)} | {reference['asset_name'] for reference in references}
    references = [{'asset_id':item['id'], 'asset_name':item['name'], 'asset_type':item['type']}
                  for item in catalog if item['name'] in used]
    return {**raw, **prepared.model_dump(mode='json'), 'asset_refs': references, 'prompt': prompt,
            'duration_seconds': float(prepared.duration.removesuffix('s'))}
