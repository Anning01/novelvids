"""Version the asset design consumed by text storyboarding, excluding generated media."""
from copy import deepcopy

from models.asset import Asset
from models.asset_variant import AssetVariant
from services.creation_agent.object_state import object_state
from services.creation_agent.tools import _digest


async def storyboard_input_version(target):
    state = await object_state(target)
    if isinstance(target, Asset):
        state.pop('metadata', None)
        state['analysis_source'] = deepcopy((target.metadata or {}).get('analysis_source'))
        state['asset_type'] = target.asset_type
        state['variants'] = [
            {'id': variant.id, **await object_state(variant)}
            for variant in await AssetVariant.filter(asset_id=target.id).order_by('id')
        ]
    elif isinstance(target, AssetVariant):
        state['asset_id'] = target.asset_id
    return _digest({'state': state, 'deleted_at': getattr(target, 'deleted_at', None)})


async def storyboard_input_versions(keys):
    versions = {}
    models = {'asset': Asset, 'variant': AssetVariant}
    for key in keys:
        kind, identifier = key.split(':')
        if kind in models:
            target = await models[kind].get(id=int(identifier))
            versions[key] = await storyboard_input_version(target)
    return versions
