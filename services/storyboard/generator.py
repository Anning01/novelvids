"""Generate one complete episode through the platform output contract."""
from schemas.scene import SceneEntity
from services.storyboard.strategies import storyboard_strategy_factory
from services.creation_agent.strict_text import require_text_execution


async def generate_storyboard(
    long_text: str,
    entities: list[SceneEntity],
    prompt_language: str = "zh",
    storyboard_strategy: str | None = None,
    creative_constraints: list[dict] | None = None,
    previously_seen_assets: list[str] | None = None,
    scene_layouts: dict | None = None,
    introduction_descriptions: dict[str, str] | None = None,
    shot_duration_range: list[int] | None = None,
    episode_pacing: dict | None = None,
    episode_max_seconds: int | None = None,
):
    from services.creation_agent.skill_execution import current_execution
    execution = current_execution.get()
    execution = require_text_execution(execution.params if execution else {})
    seen_assets = list(dict.fromkeys(previously_seen_assets or []))
    from services.creation_agent.strict_text import verify_chapter_input
    from services.creation_agent.step_context import step_context
    from services.storyboard.strict_result import storyboard_result
    await verify_chapter_input(execution.params)
    context = await step_context(execution.params)
    context_data = context.model_dump(mode='json') if context else None
    if context_data:
        asset_ids = {entity.asset_id for entity in entities}
        variant_ids = {entity.variant_id for entity in entities if entity.variant_id is not None}
        context_data['assets'] = [
            {**asset, 'variants': [variant for variant in asset.get('variants', []) if variant['id'] in variant_ids]}
            for asset in context_data['assets'] if asset['id'] in asset_ids]
        context_data['step']['asset_ids'] = [identifier for identifier in context_data['step']['asset_ids'] if identifier in asset_ids]
        context_data['step']['variant_ids'] = [identifier for identifier in context_data['step']['variant_ids'] if identifier in variant_ids]
    payload = await execution.generate_strict({'chapter': long_text,
        'entities': [entity.model_dump() for entity in entities],
        'constraints': creative_constraints or [], 'scene_layouts': scene_layouts or {},
        'previously_seen_assets': seen_assets, 'introduction_descriptions': introduction_descriptions or {},
        'episode_pacing': episode_pacing or {'preset': 'smart'}, 'episode_max_seconds': episode_max_seconds,
        'shot_duration_range': execution.params.get('shot_duration_range', shot_duration_range),
        'generate_blocking_maps': execution.params.get('generate_blocking_maps', False),
        **({'step_context': context_data} if context_data else {})})
    storyboard = storyboard_result(payload, prompt_language, entities, storyboard_strategy_factory.resolve(storyboard_strategy))
    return storyboard, {'model': execution.params['assistant_model_config_id'], 'batch_count': 1, 'usage': {},
                        'source_scene_numbers': [shot.source_scene_number for shot in storyboard.shots]}
