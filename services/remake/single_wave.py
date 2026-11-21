"""Independent source-grounded shot requests. No shot waits for another model response."""
import asyncio
import time
from contextlib import aclosing
from collections import defaultdict

from schemas.agent_workflow import RemakeShot


async def analyze_source_shots(paths, durations, evidence, gateway, strategy, saved, report, catalog):
    async def ready():
        for path, duration in zip(paths, durations, strict=True):
            yield path, duration, evidence[path.name]["interval"], len(paths)

    return await analyze_ready_shots(ready(), gateway, strategy, saved, report, catalog)


async def analyze_ready_shots(ready, gateway, strategy, saved, report, catalog):
    completed = sum(key.startswith("model:remake:RemakeShot:") and key.rsplit(":", 1)[1].isdigit() for key in saved)
    schema = RemakeShot.model_json_schema()
    tasks = []

    async def shot(i, path, previous, facts, total):
        nonlocal completed
        key = f'model:remake:RemakeShot:{i}'
        if key in saved:
            return {**saved[key], 'shot_index': i, 'file': path.name}
        result = await gateway.analyze_one(index=i, path=path, prompt='', context=facts,
            schema_name='professional_video_prompt_material', response_schema=schema, previous_path=previous)
        completed += 1
        if report:
            await report(completed, total)
        return {**result, 'shot_index': i, 'file': path.name}

    previous = previous_interval = None
    try:
        async with aclosing(ready):
            async for path, duration, interval, total in ready:
                if not tasks and report:
                    await report(completed, total)
                facts = {'assets': catalog, 'duration_seconds': duration, 'storyboard_strategy': strategy,
                         'source_interval': interval}
                if previous:
                    facts['preceding_source_interval'] = previous_interval
                tasks.append(asyncio.create_task(shot(len(tasks) + 1, path, previous, facts, total)))
                previous, previous_interval = path, interval
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return list(results)


async def stream_source_analysis(detector, source_path, directory, gateway, strategy, catalog, saved,
                                 checkpoint, report, phase_times, *, cache):
    from services.remake.checkpoints import shot_evidence, write_scene_manifest
    from services.remake.media_capacity import finish_thread, media_capacity
    from services.remake.pipeline import RemakePipelineError
    from utils.messages import localized_message

    paths, durations, evidence = [], [], {}
    started = time.monotonic()
    first_ready = None
    previous_timeline = saved.get("remake:timeline")

    async def verify(key, value):
        async def snapshot():
            return value
        if await checkpoint(key, snapshot) != value:
            raise RemakePipelineError(localized_message('切片内容或边界已变化，不能复用旧分镜'))

    async def ready():
        nonlocal first_ready
        async with media_capacity(), aclosing(detector.ready_clips(source_path, directory)) as clips:
            async for path, interval, total in clips:
                duration = interval["end_seconds"] - interval["start_seconds"]
                item = await finish_thread(shot_evidence, path, duration, interval)
                if previous_timeline is not None and (len(previous_timeline) != total or previous_timeline.get(path.name) != item):
                    raise RemakePipelineError(localized_message('切片内容或边界已变化，不能复用旧分镜'))
                await verify("remake:clip:" + path.name, {**item, "total": total})
                paths.append(path)
                durations.append(duration)
                evidence[path.name] = item
                if first_ready is None:
                    first_ready = time.monotonic()
                    phase_times["first_clip_ready_ms"] = round((first_ready - started) * 1000)
                yield path, duration, interval, total
        await verify("remake:timeline", evidence)
        if cache:
            write_scene_manifest(directory, paths, durations)
        phase_times["media_ms"] = round((time.monotonic() - started) * 1000)

    results = await analyze_ready_shots(ready(), gateway, strategy, saved, report, catalog)
    phase_times["shot_analysis_ms"] = round((time.monotonic() - first_ready) * 1000) if first_ready is not None else 0
    return paths, durations, results


def bind_shot_references(shots, assets):
    """A provisional ID is local to its shot. Bind only an unambiguous typed name."""
    by_name = defaultdict(list)
    for group, kind in (('characters', 'character'), ('scenes', 'scene'), ('objects', 'object')):
        for asset in assets.get(group, []):
            names = {asset['name'], *(asset.get('aliases') or []), *(asset.get('source_names') or [])}
            if asset.get('form_name'):
                names.add(asset['name'].partition('#')[0])
            for name in {value.strip().casefold() for value in names}:
                by_name[kind, name].append(asset)
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
