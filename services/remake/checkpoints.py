"""Resume completed model steps and local scene files for the same immutable source."""
import hashlib
import json
import math
import re
from pathlib import Path

from tortoise.expressions import Q

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


ASSET_RECEIPT_KEYS = frozenset(
    f"model:remake:{schema}:{segment}"
    for schema in ("RemakeAssets", "RemakeCastAssets", "RemakeTimedAssets")
    for segment in ("1", "1-readmit")
)


async def task_history(params):
    previous_id = params.get('retry_of_task_id')
    visited = set()
    while previous_id and previous_id not in visited:
        visited.add(previous_id)
        task = await AiTask.get_or_none(id=previous_id, task_type=AiTaskTypeEnum.remake_decomposition)
        if not task:
            break
        old = task.request_params or {}
        if any(old.get(k) != params.get(k) for k in
               ('remake_source_id', 'chapter_id', 'novel_id', 'team_id', 'user_id', 'prompt_language', 'model_config_id',
                'remake_context_version', 'remake_shot_limit', 'remake_identity_evidence', 'remake_cast_appearances', 'remake_asset_appearances', 'remake_short_storyboard', 'source_checksum', 'skill_snapshot', 'remake_block_size', 'remake_episode_count')):
            break
        yield task
        previous_id = old.get('retry_of_task_id')


async def completed_outputs(params, *, keys_only=False):
    results = {}
    async for task in task_history(params):
        fields = ('key',) if keys_only else ('key', 'result')
        rows = await AgentOperation.filter(Q(key__startswith='remake:clip:') | Q(key__startswith='model:remake:') | Q(key__startswith="model:structured:RemakeContinuityVerdict:") | Q(key__startswith="model:structured:RemakeSpeechEvidence:") | Q(key__in=['remake:catalog', 'remake:bindings', 'remake:timeline']),
                                           task=task, state='completed').values(*fields)
        for row in rows:
            key = row["key"]
            results.setdefault(key, row.get("result"))
            if key in ASSET_RECEIPT_KEYS:
                results.setdefault("model:remake:RemakeAssets:1", row.get("result"))
            if key == "model:remake:RemakeShortStoryboard:1-readmit":
                results.setdefault(key.removesuffix("-readmit"), row.get("result"))
    return results


async def _rate_limited_outcome(task, receipt, child):
    """Some compatible gateways report an explicit upstream admission denial inside the stream."""
    from models.creation_agent import AgentMessage
    if not child or child.status != TaskStatusEnum.failed:
        return None
    segment = receipt.key.rsplit(":", 1)[-1]
    number = re.fullmatch(r"(?:draft-)?(\d+)(?:-readmit|-(?:dialogue|narration)-[0-9a-f]+)?", segment)
    if not number:
        return None
    segment = number[1]
    message = task.error_message or ""
    from services.remake.analysis_capacity import provider_pressure
    # Require this exact segment's terminal error, not a coincidental failure elsewhere in the batch.
    if task.request_params.get("remake_context_version", 0) >= 3:
        denied = (receipt.result or {}).get("provider_capacity_denial") is True
    else:
        denied = provider_pressure(message) and (
            f"第 {segment} 个视频片段分析失败：" in message
            or re.search(rf"Video segment {segment}\b[^:]*:", message, re.I)
        )
    if not denied:
        return None
    record = await AgentMessage.filter(task=child, role="assistant").only("usage").first()
    calls = (record.usage or {}).get("calls") if record else None
    if not calls or any(c.get("status") != "failed" or c.get("finish_reason") or c.get("usage_reported")
                        or (c.get("usage") or {}).get("output_tokens") for c in calls):
        return None
    # A streamed error can carry chargeable partial text. Preserve that evidence and
    # distinguish a terminal interrupted response from a request with an unknown outcome.
    from pydantic_core import from_json
    response = await AgentOperation.filter(task=child, key__startswith="model-response:", state="completed").order_by("-id").first()
    if not response:
        return {"reason": "admission_rejected", "retryable": True}
    partial = {}
    for message in response.result.get("messages", []):
        for part in message.get("parts", []):
            if part.get("part_kind") != "text":
                continue
            try:
                parsed = from_json(part.get("content", ""), allow_partial=True)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                partial = {key: parsed[key] for key in ('description', 'actions', 'dialogue', 'narration') if key in parsed}
    return {"reason": "rate_limited_stream_ended", "retryable": True, "partial": partial}


async def reconcile_retry(previous):
    """Do not replay an external step with an unknown outcome in a fresh continuity attempt."""
    from uuid import uuid5
    from schemas.agent_workflow import RemakeAssets, RemakeCastAssets, RemakeShot, RemakeTimedAssets
    from schemas.remake_short import RemakeShortStoryboard
    from schemas.remake import RemakeContinuityVerdict, RemakeSpeechEvidence
    from services.remake.output_recovery import recover_shot_output
    from exceptions.remake import RemakeError
    from utils.messages import localized_message
    params = {**previous.request_params, "retry_of_task_id": str(previous.id)}
    if not params.get("remake_context_version"):
        return
    done = await completed_outputs(params, keys_only=True)
    async for task in task_history(params):
        uncertain = await AgentOperation.filter(Q(key__startswith="model:remake:") | Q(key__startswith="model:structured:RemakeContinuityVerdict:") | Q(key__startswith="model:structured:RemakeSpeechEvidence:"),
                                                task=task, external=True, state__in=["uncertain", "running"]).order_by("key")
        for receipt in uncertain:
            if receipt.key in done:
                continue
            child = await AiTask.get_or_none(id=uuid5(task.id, receipt.key))
            is_shot = receipt.key.startswith("model:remake:RemakeShot:")
            schema = {"RemakeTimedAssets": RemakeTimedAssets, "RemakeCastAssets": RemakeCastAssets, "RemakeShortStoryboard": RemakeShortStoryboard, "RemakeContinuityVerdict": RemakeContinuityVerdict, "RemakeSpeechEvidence": RemakeSpeechEvidence,
                      "RemakeShot": RemakeShot, "RemakeAssets": RemakeAssets}[receipt.key.split(":")[2]]
            result = None
            if child and child.status == TaskStatusEnum.completed and child.response_data:
                result = schema.model_validate(child.response_data)
            elif schema is RemakeShortStoryboard:
                from services.remake.output_recovery import latest_response_text, recover_short_rows
                manifest = await AgentOperation.get_or_none(task=task, key="remake:short-input", state="completed")
                if manifest:
                    intervals = manifest.result["intervals"]
                    text = await latest_response_text(task.id, receipt.key)
                    for i, value in recover_short_rows(text, intervals).items():
                        key = f"model:remake:RemakeShot:{i}"
                        local, _ = await AgentOperation.get_or_create(task=task, key=key,
                            defaults={"state": "completed", "result": value})
                        if not local.external and local.state != "completed":
                            await AgentOperation.filter(id=local.id, external=False).exclude(state="completed").update(state="completed", result=value)
                        if local.state == "completed" or not local.external:
                            done[key] = None
                    if intervals and all(f"model:remake:RemakeShot:{span['sequence']}" in done for span in intervals):
                        # No further model request is needed. Keep the original external outcome intact.
                        continue
            elif is_shot:
                result = await recover_shot_output(task.id, receipt.key.rsplit(":", 1)[1])
            if result is None and (outcome := await _rate_limited_outcome(task, receipt, child)):
                await AgentOperation.filter(id=receipt.id, state__in=["uncertain", "running"]).update(state="failed", result=outcome)
                continue
            if result is None:
                raise RemakeError(409, "REMAKE_AWAITING_RECEIPT", localized_message("上次请求的结果尚未确认，请稍后核对"))
            await AgentOperation.filter(id=receipt.id).update(state="completed", result=result.model_dump(mode="json"))
            done[receipt.key] = None


def read_scene_manifest(directory: Path):
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    try:
        entries = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(entries, list) or not entries:
        return None
    paths, durations = [], []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            return None
        path = directory / item["file"]
        duration = item.get("duration")
        if (path.parent != directory or not path.is_file() or path.stat().st_size != item.get("size")
                or isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or duration <= 0):
            return None
        paths.append(path)
        durations.append(duration)
    return paths, durations


def write_scene_manifest(directory, paths, durations):
    entries = [{'file':path.name, 'size':path.stat().st_size, 'duration':duration}
               for path, duration in zip(paths, durations, strict=True)]
    temporary = directory / 'manifest.tmp'
    temporary.write_text(json.dumps(entries))
    temporary.replace(directory / 'manifest.json')


def clip_evidence(directory, paths, durations):
    boundaries_file = directory / "boundaries.json"
    boundaries = json.loads(boundaries_file.read_text()) if boundaries_file.is_file() else {}
    evidence = {}
    for path, duration in zip(paths, durations, strict=True):
        evidence[path.name] = shot_evidence(path, duration, boundaries.get(path.name))
    return evidence


def shot_evidence(path, duration, interval):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "duration": duration, "interval": interval}


def scene_cache_directory(source):
    from config import settings
    return Path(settings.STUDIO_MEDIA_CACHE_PATH).resolve().parent / "remake-scenes" / str(source.id) / source.checksum


async def shot_progress(task, source, current_rows=None):
    """Map durable receipts to original clip numbers without loading their generated text."""
    if current_rows is None:
        current_rows = await AgentOperation.filter(Q(key__startswith="model:remake:") | Q(key__startswith="capacity:remake:"),
                                                   task=task).values_list("key", "state")
    keys = {key for key, state in current_rows if state == "completed"}
    if task.request_params.get("retry_of_task_id"):
        keys.update(await completed_outputs(task.request_params, keys_only=True))
    if keys.intersection(ASSET_RECEIPT_KEYS):
        keys.add('model:remake:RemakeAssets:1')
    prefix = 'model:remake:RemakeShot:'
    indices = {int(key[len(prefix):]) for key in keys if key.startswith(prefix) and key[len(prefix):].isdigit()}
    manifest = read_scene_manifest(scene_cache_directory(source))
    total = len(manifest[0]) if manifest else None
    rows = [(key,state) for key,state in current_rows if key.startswith(prefix)]
    states = {int(key[len(prefix):]): state for key, state in rows if key[len(prefix):].isdigit()}
    for key in keys:
        suffix = key.removeprefix(prefix)
        if key.startswith(prefix + "draft-") and suffix[6:].isdigit():
            states.setdefault(int(suffix[6:]), "boundary_pending")
    for key, state in rows:
        suffix = key.removeprefix(prefix + "draft-")
        if key.startswith(prefix + "draft-") and suffix.isdigit():
            states.setdefault(int(suffix), "boundary_pending" if state == "completed" else state)
    if task.request_params.get("remake_context_version"):
        waiting = [key for key, state in current_rows if key.startswith("capacity:remake:") and state == "waiting_capacity"]
        for key in waiting:
            index = key.rsplit(":", 1)[1].removeprefix("draft-")
            if index.isdigit() and states.get(int(index)) in (None, "running", "pending"):
                states[int(index)] = "waiting_capacity"
    if total and task.request_params.get("remake_short_storyboard"):
        batch_states = dict(current_rows)
        state = batch_states.get("model:remake:RemakeShortStoryboard:1-readmit") or batch_states.get("model:remake:RemakeShortStoryboard:1")
        if state in {"running", "failed", "uncertain"}:
            for index in range(1, total + 1):
                states.setdefault(index, state)
    for index in indices:
        states[index] = 'completed'
    states = {i: state for i, state in states.items() if i > 0 and (not total or i <= total)}
    confirmed = sum(state == 'completed' for state in states.values())
    stage, progress = 'queued', 0
    if 'model:remake:RemakeAssets:1' in keys:
        stage, progress = 'detecting_scenes', 42
    if stage == 'detecting_scenes' and (total or confirmed):
        stage = 'generating_storyboards'
        progress = 55 + round(32 * confirmed / total) if total else max(55, min(task.progress or 0, 87))
        if total and confirmed == total:
            stage, progress = 'persisting', 88
    return stage, progress, confirmed, total, states


async def resume_position(task, source):
    stage, progress, completed, total, _ = await shot_progress(task, source)
    return stage, progress, completed, total


async def partial_retry(task, total):
    """Explicit retry reuses saved clips and retries every unfinished clip."""
    if not total:
        return [], 0
    saved = await completed_outputs({**task.request_params, 'retry_of_task_id': str(task.id)}, keys_only=True)
    remaining = sum(f'model:remake:RemakeShot:{index}' not in saved for index in range(1, total + 1))
    return [], remaining
