"""Restorable sheet images reuse image tasks; no separate version store."""
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException
from tortoise import connections
from models.ai_task import AiTask
from models.scene import Scene
from services.creation_objects import project_write
from services.oss import normalize_media_url, resolve_media_url
from services.video_enhancement.media import digest
from utils.messages import localized_message as msg

SHEET_OPERATIONS = {'storyboard_sheet', 'storyboard_sheet_edit'}


def current_sheet(scene):
    sheet = deepcopy((scene.metadata or {}).get('storyboard_sheet') or {})
    sheet['image_url'] = normalize_media_url(sheet.get('image_url') or sheet.get('previous_image_url')) or ''
    return sheet


def sheet_revision(scene):
    sheet = current_sheet(scene)
    return digest([sheet.get('revision'), sheet.get('task_id'), sheet.get('image_url')])


def task_sheet(task, source=False):
    params = task.request_params or {}
    if params.get('operation') not in SHEET_OPERATIONS:
        raise HTTPException(404, msg('线稿记录不存在'))
    if source:
        sheet = deepcopy(params.get('source_sheet') or {})
    else:
        result = task.response_data or {}
        if task.status != 3 or not result.get('images'):
            raise HTTPException(409, msg('只有生成成功的线稿可以恢复'))
        sheet = deepcopy(result.get('sheet') or {
            'task_id': str(task.id), 'image_url': result['images'][0],
            'scene_fingerprint': params.get('scene_fingerprint'),
            'video_prompt': params.get('sheet', {}).get('video_prompt', ''),
            'video_guidance': params.get('sheet', {}).get('video_guidance', ''),
        })
    sheet['image_url'] = sheet.get('image_url') or sheet.get('previous_image_url')
    if not sheet.get('image_url'):
        raise HTTPException(404, msg('线稿记录没有可恢复的图片'))
    sheet['image_url'] = normalize_media_url(sheet['image_url']) or sheet['image_url']
    sheet['status'] = 'completed'
    sheet.pop('previous_image_url', None)
    return sheet


async def sheet_history(scene_id):
    scene = await Scene.get(id=scene_id)
    db = connections.get('default')
    # Filter before LIMIT on both supported databases; never scan unrelated projects' task payloads.
    expression, placeholder = ("request_params->>'scene_id'", '$1') if db.capabilities.dialect == 'postgres' else ("CAST(json_extract(request_params, '$.scene_id') AS TEXT)", '?')
    rows = await db.execute_query_dict(f'SELECT id FROM ai_tasks WHERE task_type=2 AND {expression}={placeholder} ORDER BY created_at DESC LIMIT 100', [str(scene_id)])
    tasks = await AiTask.filter(id__in=[row['id'] for row in rows]).order_by('-created_at')
    current = current_sheet(scene)
    history, seen = [], set()
    # Prefer the original task's date/instruction; source snapshots only fill missing history.
    for source in (False, True):
        for task in tasks:
            if task.request_params.get('operation') not in SHEET_OPERATIONS:
                continue
            try:
                sheet = task_sheet(task, source)
            except HTTPException:
                continue
            url = sheet['image_url']
            if url in seen:
                continue
            seen.add(url)
            history.append({'task_id': str(task.id), 'source': source,
                'image_url': resolve_media_url(url) or url, 'is_current': url == current.get('image_url'),
                'instruction': '' if source else task.request_params.get('edit_instruction', ''),
                'created_at': task.created_at.isoformat(), 'model': task.request_params.get('model'),
                'saved': True if source else bool((task.response_data or {}).get('saved'))})
    active = await AiTask.get_or_none(id=current.get('task_id')) if current.get('task_id') else None
    return {'scene_id': scene.id, 'sequence': scene.sequence, 'revision': sheet_revision(scene),
            'task_id': str(active.id) if active else None, 'task_status': active.status if active else None,
            'current_image_url': resolve_media_url(current.get('image_url')) or current.get('image_url'), 'items': history}


async def restore_sheet(scene_id, request):
    scene = await Scene.get(id=scene_id).prefetch_related('chapter')
    task = await AiTask.get_or_none(id=request.task_id)
    if not task or task.request_params.get('scene_id') != scene.id or task.request_params.get('novel_id') != scene.chapter.novel_id:
        raise HTTPException(404, msg('线稿记录不属于当前分镜'))
    sheet = task_sheet(task, request.source)
    async with project_write(scene.chapter.novel_id):
        await scene.refresh_from_db()
        if sheet_revision(scene) != request.expected_revision:
            raise HTTPException(409, msg('当前线稿已变化，请刷新后重试'))
        sheet['revision'] = str(uuid4())
        scene.metadata = {**(scene.metadata or {}), 'storyboard_sheet': sheet}
        await scene.save(update_fields=['metadata', 'updated_at'])
    return scene
