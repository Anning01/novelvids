"""Resume completed model steps and local scene files for the same immutable source."""
import json
from pathlib import Path

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from utils.enums import AiTaskTypeEnum


async def completed_outputs(params):
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
        rows = await AgentOperation.filter(task=task, state='completed', key__startswith='model:remake:').values('key', 'result')
        for row in rows:
            results.setdefault(row['key'], row['result'])
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
