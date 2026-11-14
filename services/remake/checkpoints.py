"""Resume completed model steps and local scene files for the same immutable source."""
import json
from pathlib import Path

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from utils.enums import AiTaskTypeEnum


async def completed_outputs(params, *, keys_only=False):
    results = {}
    previous_id = params.get('retry_of_task_id')
    visited = set()
    while previous_id and previous_id not in visited:
        visited.add(previous_id)
        task = await AiTask.get_or_none(id=previous_id, task_type=AiTaskTypeEnum.remake_decomposition)
        if not task:
            break
        old = task.request_params or {}
        if any(old.get(k) != params.get(k) for k in
               ('remake_source_id', 'chapter_id', 'novel_id', 'team_id', 'user_id', 'prompt_language', 'model_config_id')):
            break
        fields = ('key',) if keys_only else ('key', 'result')
        rows = await AgentOperation.filter(task=task, state='completed', key__startswith='model:remake:').values(*fields)
        for row in rows:
            results.setdefault(row['key'], row.get('result'))
        previous_id = old.get('retry_of_task_id')
    return results


def read_scene_manifest(directory: Path):
    manifest = directory / 'manifest.json'
    if not manifest.is_file():
        return None
    try:
        entries = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return None
    paths = [directory / item['file'] for item in entries]
    if not paths or any(path.parent != directory or not path.is_file() or path.stat().st_size != item['size']
                        for path, item in zip(paths, entries)):
        return None
    return paths, [item['duration'] for item in entries]


def write_scene_manifest(directory, paths, durations):
    entries = [{'file':path.name, 'size':path.stat().st_size, 'duration':duration}
               for path, duration in zip(paths, durations, strict=True)]
    temporary = directory / 'manifest.tmp'
    temporary.write_text(json.dumps(entries))
    temporary.replace(directory / 'manifest.json')


def scene_cache_directory(source):
    from config import settings
    return Path(settings.STUDIO_MEDIA_CACHE_PATH).resolve().parent / "remake-scenes" / str(source.id) / source.checksum


async def resume_position(task, source):
    """Recover paid outputs by original index, including this attempt and its ancestors."""
    keys = await completed_outputs({**task.request_params, 'retry_of_task_id': str(task.id)}, keys_only=True)
    indices = sorted(int(key.rsplit(':', 1)[1]) for key in keys if key.startswith('model:remake:RemakeShot:')
                     and key.rsplit(':', 1)[1].isdigit())
    manifest = read_scene_manifest(scene_cache_directory(source))
    total = len(manifest[0]) if manifest else None
    if total:
        indices = [i for i in indices if 1 <= i <= total]
    stage, progress = 'queued', 0
    if 'model:remake:RemakeAssets:1' in keys:
        stage, progress = 'detecting_scenes', 42
    if stage == 'detecting_scenes' and (total or indices):
        stage = 'generating_storyboards'
        progress = 55 + round(32 * len(indices) / total) if total else max(55, min(task.progress or 0, 87))
        if total and len(indices) == total:
            stage, progress = 'persisting', 88
    return stage, progress, len(indices), total


async def partial_retry(task, total):
    """Keep uncertain clip submissions out of every descendant attempt."""
    held = set(task.request_params.get('held_shots', []))
    operations = await AgentOperation.filter(task=task, external=True, state__in=['uncertain', 'running']).values_list('key', flat=True)
    prefix = 'model:remake:RemakeShot:'
    for key in operations:
        index = key.removeprefix(prefix)
        if not key.startswith(prefix) or not index.isdecimal():
            return [], 0
        held.add(int(index))
    if not held or not total or any(i < 1 or i > total for i in held):
        return [], 0
    saved = await completed_outputs({**task.request_params, 'retry_of_task_id': str(task.id)}, keys_only=True)
    if 'model:remake:RemakeAssets:1' not in saved:
        return [], 0
    remaining = {i for i in range(1, total + 1) if f'{prefix}{i}' not in saved}
    return sorted(held & remaining), len(remaining - held)
