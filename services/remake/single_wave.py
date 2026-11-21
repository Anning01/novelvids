"""Independent source-grounded shot requests. No shot waits for another model response."""
import asyncio
from collections import defaultdict

from schemas.agent_workflow import RemakeShot


async def analyze_source_shots(paths, durations, evidence, gateway, strategy, saved, report, catalog):
    completed = sum(f'model:remake:RemakeShot:{i}' in saved for i in range(1, len(paths) + 1))
    if report:
        await report(completed, len(paths))

    async def shot(i, path):
        nonlocal completed
        key = f'model:remake:RemakeShot:{i}'
        if key in saved:
            return {**saved[key], 'shot_index': i, 'file': path.name}
        previous = paths[i - 2] if i > 1 else None
        facts = {'assets': catalog, 'duration_seconds': durations[i - 1], 'storyboard_strategy': strategy,
                 'source_interval': evidence[path.name]['interval']}
        if previous:
            facts['preceding_source_interval'] = evidence[previous.name]['interval']
        result = await gateway.analyze_one(index=i, path=path, prompt='', context=facts,
            schema_name='professional_video_prompt_material', response_schema=RemakeShot.model_json_schema(),
            previous_path=previous)
        completed += 1
        if report:
            await report(completed, len(paths))
        return {**result, 'shot_index': i, 'file': path.name}

    results = await asyncio.gather(*(shot(i, p) for i, p in enumerate(paths, 1)), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def bind_shot_references(shots, assets):
    """A provisional ID is local to its shot. Bind only an unambiguous typed name."""
    by_name = defaultdict(list)
    for group, kind in (('characters', 'character'), ('scenes', 'scene'), ('objects', 'object')):
        for asset in assets.get(group, []):
            names = {asset['name'], *(asset.get('aliases') or []), *(asset.get('source_names') or [])}
            if asset.get('form_name'):
                names.add(asset['name'].partition('#')[0])
            for name in names:
                by_name[kind, name.strip().casefold()].append(asset)
    bound = []
    for shot in shots:
        resolved, missing = [], []
        for ref in shot['asset_refs']:
            matches = by_name[ref['asset_type'], ref['asset_name'].strip().casefold()]
            if len(matches) == 1:
                item = matches[0]
                resolved.append({**ref, 'asset_id': item['id'], 'asset_name': item['name']})
            else:
                missing.append(ref)
        bound.append({**shot, 'asset_refs': resolved, **({'unresolved_asset_refs': missing} if missing else {})})
    return bound
