"""Independent source-grounded shot requests. No shot waits for another model response."""
import asyncio
import time
from contextlib import aclosing
from collections import defaultdict



async def analyze_source_shots(paths, durations, evidence, gateway, strategy, saved, report, catalog):
    async def ready():
        for path, duration in zip(paths, durations, strict=True):
            yield path, duration, evidence[path.name]["interval"], len(paths)

    return await analyze_ready_shots(ready(), gateway, strategy, saved, report, catalog)


async def analyze_ready_shots(ready, gateway, strategy, saved, report, catalog):
    completed = sum(key.startswith("model:remake:RemakeShot:") and key.rsplit(":", 1)[1].isdigit() for key in saved)
    from services.creation_agent.skill_execution import current_execution
    from schemas.remake_motion import shot_contracts
    shot_schema, _ = shot_contracts(getattr(current_execution.get(), "params", {}))
    schema = shot_schema.model_json_schema()
    tasks = []
    returned = {}

    async def shot(i, path, previous, facts, total):
        nonlocal completed
        key = f'model:remake:RemakeShot:{i}'
        if key in saved:
            return {**saved[key], 'shot_index': i, 'file': path.name, 'source_interval': facts['source_interval']}
        prior = returned.get(i - 1) or saved.get(f'model:remake:RemakeShot:{i-1}')
        if facts['source_interval'] and 'output_seconds' in facts['source_interval'] and prior:
            from services.remake.handoff import end_state_memory
            facts['confirmed_handoff'] = end_state_memory(prior, i - 1)
        result = await gateway.analyze_one(index=i, path=path, prompt='', context=facts,
            schema_name='professional_video_prompt_material', response_schema=schema, previous_path=previous)
        returned[i] = result
        completed += 1
        if report:
            await report(completed, total)
        return {**result, 'shot_index': i, 'file': path.name, 'source_interval': facts['source_interval']}

    previous = previous_interval = None
    try:
        async with aclosing(ready):
            async for path, duration, interval, total in ready:
                if not tasks and report:
                    await report(completed, total)
                facts = {'assets': catalog, 'duration_seconds': interval.get('output_seconds', duration) if interval else duration, 'storyboard_strategy': strategy,
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
    timed = []
    for group, kind in (('characters', 'character'), ('scenes', 'scene'), ('objects', 'object')):
        for asset in assets.get(group, []):
            if asset.get('appearances'):
                timed.append((kind, asset))
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
        interval = shot.get('source_interval')
        present_names = []
        if interval:
            resolved_ids = {ref['asset_id'] for ref in resolved}
            for kind, asset in timed:
                if any(span['start_seconds'] < interval['end_seconds'] and interval['start_seconds'] < span['end_seconds']
                       for span in asset['appearances']):
                    present_names.append(asset['name'])
                    if asset['id'] not in resolved_ids:
                        resolved.append({'asset_id': asset['id'], 'asset_name': asset['name'], 'asset_type': kind})
                        resolved_ids.add(asset['id'])
        item = {**shot, 'asset_refs': resolved, **({'unresolved_asset_refs': missing} if missing else {})}
        if present_names and shot.get('visible_asset_names') is not None:
            item['visible_asset_names'] = list(dict.fromkeys([*shot['visible_asset_names'], *present_names]))
        bound.append(item)
    return bound


async def analyze_short_storyboard(source_path, paths, evidence, gateway, strategy, saved, checkpoint, report, catalog, params):
    """Read the short film once, then commit each validated shot under its normal receipt key."""
    from schemas.remake_motion import shot_contracts
    _, RemakeShortStoryboard = shot_contracts(params)
    direct = params.get("remake_action_memory") == "timeline"
    from services.remake.delivered_output import delivered_batch
    results = {}
    intervals = []
    for i, path in enumerate(paths, 1):
        stored = saved.get(f'model:remake:RemakeShot:{i}')
        if stored is not None:
            results[i] = stored
        else:
            span = {"sequence": i, **evidence[path.name]["interval"]}
            prior = saved.get(f'model:remake:RemakeShot:{i-1}')
            if "output_seconds" in span and prior:
                from services.remake.handoff import end_state_memory
                span["confirmed_handoff"] = end_state_memory(prior, i-1)
            intervals.append(span)
    await report(len(results), len(paths))
    async def save(i, material):
        async def value():
            return material
        results[i] = await checkpoint(f"model:remake:RemakeShot:{i}", value)

    if intervals:
        # The original batch receipt survives a crash between individual local commits.
        stored_batch = saved.get("model:remake:RemakeShortStoryboard:1")
        if stored_batch is not None and direct:
            material = delivered_batch(stored_batch, [{"sequence": i, **evidence[p.name]["interval"]} for i,p in enumerate(paths,1)])
        elif stored_batch is not None:
            batch = RemakeShortStoryboard.model_validate({key: stored_batch[key] for key in ("looks", "shots")})
            indices = {shot.sequence for shot in batch.shots}
            source_intervals = [{"sequence": i, **evidence[p.name]["interval"]} for i,p in enumerate(paths,1)
                                if i in indices]
            material = batch.materialize(source_intervals)
        else:
            from services.remake.short_admission import run_admitted
            async def input_manifest():
                return {"intervals": intervals}
            if await checkpoint("remake:short-input", input_manifest) != {"intervals": intervals}:
                raise ValueError("Requested shot intervals changed")
            async def request(segment):
                return await gateway.analyze_one(index=1, path=source_path, prompt="", schema_name="short_video_storyboard",
                    response_schema=RemakeShortStoryboard.model_json_schema(), include_segment_metadata=False,
                    context={"assets": catalog, "intervals": intervals, "storyboard_strategy": strategy},
                    **({"readmission_segment": segment} if segment else {}))
            try:
                raw = await run_admitted(request, gateway.config, params, "RemakeShortStoryboard")
            except (Exception, asyncio.CancelledError) as exc:
                from services.remake.output_recovery import latest_response_text, recover_short_rows
                material = {}
                for segment in ("1-readmit", "1"):
                    text = await latest_response_text(params["task_id"], f"model:remake:RemakeShortStoryboard:{segment}")
                    if text:
                        material = recover_short_rows(text, intervals, RemakeShortStoryboard)
                        break
                for i, item in material.items():
                    await save(i, item)
                if isinstance(exc, asyncio.CancelledError) or len(material) != len(intervals):
                    raise
            else:
                material = delivered_batch(raw, intervals) if direct else RemakeShortStoryboard.model_validate(raw).materialize(intervals)
        if not direct and not {span["sequence"] for span in intervals}.issubset(material):
            raise ValueError("Saved storyboard does not cover every unfinished source interval")
        for span in intervals:
            i = span["sequence"]
            if i not in results and i in material:
                await save(i, material[i])
        await report(len(results), len(paths))
    return [{**results[i], "shot_index": i, "file": path.name, "source_interval": evidence[path.name]["interval"]}
            for i,path in enumerate(paths,1) if i in results]
