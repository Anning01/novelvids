"""Load prior visible asset appearances in narrative order, excluding a regenerated chapter."""

from collections.abc import Sequence
from types import SimpleNamespace

from models.chapter import Chapter
from models.scene import Scene
from prompts.storyboard import visible_storyboard_assets
from schemas.scene import SceneEntity


async def previously_seen_assets(chapter: Chapter, entities: Sequence[SceneEntity]) -> list[str]:
    assets = {}
    for entity in entities:
        if entity.asset_id is not None:
            assets.setdefault(entity.asset_id, []).append(entity)
    if not assets:
        return []
    scenes = await Scene.filter(
        chapter__novel_id=chapter.novel_id, chapter__number__lt=chapter.number,
        assets__id__in=list(assets),
    ).distinct().only("id", "prompt_params").prefetch_related("assets")
    seen = set()
    for scene in scenes:
        linked = [entity for asset in scene.assets for entity in assets.get(asset.id, [])]
        params = scene.prompt_params or {}
        if any(key in params for key in ("visual_prose", "actions", "spatial_relationships", "environment", "segments")):
            seen.update(visible_storyboard_assets(SimpleNamespace(**params), linked))
        else:
            # Historical free-text shots have only their explicit asset relations.
            seen.update(entity.name for entity in linked)
    seen_ids = {entity.asset_id for entity in entities if entity.name in seen and entity.asset_id is not None}
    return [entity.name for entity in entities if entity.name in seen or entity.asset_id in seen_ids]
