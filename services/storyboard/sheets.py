"""One persisted line-art image per existing shot, using the standard image task."""

import hashlib
import json

from fastapi import HTTPException

from models.ai_task import AiTask
from models.scene import Scene
from prompts.skill_pack import read_skill
from prompts.skills.scripts.storyboard_sheets import prepare
from services.creation_objects import project_write
from services.image_generation.capabilities import validate_selection
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.messages import localized_message


def sheet_for(scene, language):
    from utils.prompt_language import normalize_prompt_language
    data = {**(scene.prompt_params or {}), 'sequence': scene.sequence, 'prompt': scene.prompt}
    templates = json.loads(read_skill('storyboard_sheet_templates'))[normalize_prompt_language(language)]
    return {**prepare({'shots': [data]}, templates)[0], 'video_guidance': templates['video']}


def scene_fingerprint(scene):
    return hashlib.sha256(json.dumps([scene.prompt, scene.prompt_params, scene.description], sort_keys=True).encode()).hexdigest()


async def submit_sheet(scene_id, *, model_config_id: int, team_id=None, user_id=None):
    if not model_config_id:
        raise HTTPException(422, localized_message('请选择生图模型'))
    from uuid import UUID, uuid5
    from services.creation_agent.submissions import submission
    envelope = submission.get()
    token = None
    if envelope:
        identifier = uuid5(UUID(envelope['submission_id']), f'storyboard-sheet:{scene_id}:{model_config_id}')
        token = submission.set({**envelope, 'submission_id': str(identifier)})
    try:
        return await _submit_sheet(scene_id, team_id=team_id, user_id=user_id, model_config_id=model_config_id)
    finally:
        if token is not None:
            submission.reset(token)


async def _submit_sheet(scene_id, *, model_config_id: int, team_id=None, user_id=None):
    from controllers.config import ai_model_config_controller, general_config_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import prepare_workflow
    scene = await Scene.get(id=scene_id).prefetch_related('chapter__novel')
    from services.video_enhancement.sources import require_generation_scope
    await require_generation_scope(scene.chapter.novel_id, team_id)
    if not scene.chapter.novel.storyboard_enabled:
        raise HTTPException(409, localized_message('请先在剧本页开启逐镜线稿故事版'))
    config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image, model_config_id, team_id=team_id)
    selection = validate_selection(config.image_model_type, clarity=None, aspect_ratio=scene.chapter.novel.aspect_ratio or '16:9', output_format='png', generation_count=1)
    language = await general_config_controller.get_prompt_language()
    async with project_write(scene.chapter.novel_id) as db:
        scene = await Scene.get(id=scene_id).prefetch_related('chapter__novel')
        if not scene.chapter.novel.storyboard_enabled:
            raise HTTPException(409, localized_message('请先在剧本页开启逐镜线稿故事版'))
        from services.creation_agent.submissions import previous_submission, bind_submission
        params = dict(operation='storyboard_sheet', novel_id=scene.chapter.novel_id, chapter_id=scene.chapter_id,
            scene_id=scene.id, team_id=team_id, user_id=user_id, model_config_id=config.id,
            model=config.model, prompt_language=language, clarity=selection.clarity, resolution=selection.provider_size,
            aspect_ratio=selection.aspect_ratio, output_format='png', generation_count=1,
            sheet=sheet_for(scene, language), scene_fingerprint=scene_fingerprint(scene),
            source_sheet=(scene.metadata or {}).get('storyboard_sheet') or {})
        previous = await previous_submission(AiTaskTypeEnum.reference_image, params, db)
        if previous:
            return previous
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.reference_image, status__in=[TaskStatusEnum.pending, TaskStatusEnum.running, TaskStatusEnum.queued]).using_db(db):
            if (task.request_params or {}).get('scene_id') == scene.id and (task.request_params or {}).get('operation') in {'storyboard_sheet', 'storyboard_sheet_edit'}:
                if task.request_params.get('model_config_id') != config.id:
                    raise HTTPException(409, localized_message('本镜已有使用其他模型的线稿任务，请等待完成'))
                return await bind_submission(task, params)
        prepared = await prepare_workflow(params)
        for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id'):
            prepared.pop(key, None)
        task = await ai_task_executor.submit(AiTaskTypeEnum.reference_image, prepared, db_connection=db)
        scene.metadata = {**(scene.metadata or {}), 'storyboard_sheet': {
            'task_id': str(task.id), 'status': 'pending', 'previous_image_url': (scene.metadata or {}).get('storyboard_sheet', {}).get('image_url') or (scene.metadata or {}).get('storyboard_sheet', {}).get('previous_image_url')}}
        await scene.save(update_fields=['metadata', 'updated_at'])
        return task


async def parent_cancelled(params):
    identifier = params.get('origin_run_id')
    return bool(identifier and await AiTask.filter(id=identifier, status=TaskStatusEnum.cancelled).exists())


async def execute_sheet(params):
    from controllers.config import ai_model_config_controller
    from services.creation_agent.skill_execution import current_execution
    from services.reference.generator import generate_for_sora_consistency
    from services.reference.handler import _persist_generated_image
    from services.image_inputs import resolve_reference_images
    from models.asset import Asset
    execution = current_execution.get()
    if execution:
        await execution.before_request()
    if await parent_cancelled(params):
        raise ValueError(localized_message('任务已停止'))
    scene = await Scene.get(id=params['scene_id'], chapter__novel_id=params['novel_id']).prefetch_related('chapter__novel', 'assets')
    if not scene.chapter.novel.storyboard_enabled or scene_fingerprint(scene) != params['scene_fingerprint']:
        raise ValueError(localized_message('分镜或故事版设置已修改，请重新生成'))
    config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image, params['model_config_id'], team_id=params.get('team_id'))
    from services.video.asset_resolver import normalize_selected_variant_ids, select_asset_variants
    selected = normalize_selected_variant_ids((scene.metadata or {}).get('asset_variant_ids'))
    references, identities = [], []
    for asset in await Asset.filter(scenes__id=scene.id).prefetch_related('variants'):
        for variant in select_asset_variants(asset, scene.chapter.number, selected):
            images = variant.images if variant else []
            identities.append({'name': asset.canonical_name, 'variant': variant.name if variant else None,
                'visual_description': variant.base_traits if variant else asset.base_traits})
            image = next((item.get('url') if isinstance(item, dict) else item for item in images if item), None)
            if not variant:
                image = image or asset.main_image
            if image:
                references.append(image)
    references = resolve_reference_images(references)
    selection = validate_selection(config.image_model_type, clarity=params['clarity'], aspect_ratio=params['aspect_ratio'], output_format='png', generation_count=1)
    images = await generate_for_sora_consistency({'base_traits': params['sheet']['image_prompt'] + '\n\n' + json.dumps({'reference_assets': identities}, ensure_ascii=False)},
        base_url=config.base_url, api_key=config.api_key, model=config.model, api_protocol=config.api_protocol,
        resolution=selection.provider_size, aspect_ratio=selection.aspect_ratio, reference_images=references, count=1)
    if len(images) != 1:
        raise ValueError(localized_message('故事版须返回一张图片'))
    # The shared media store uses an ID namespace; the suffix separates scene sheets from asset images.
    url = await _persist_generated_image(images[0], scene.id, f'_storyboard_{params["task_id"]}')
    return await apply_sheet_result(scene, params, url, len(references))


async def enqueue_chapter_sheets(chapter_id, scene_ids, model_id, team_id, user_id, *, batch_id):
    """Publish the complete sheet queue in one transaction with stable per-shot receipts."""
    from models.chapter import Chapter
    from services.creation_agent.submissions import submission
    chapter = await Chapter.get(id=chapter_id)
    tasks = []
    async with project_write(chapter.novel_id):
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")
        selected = set(scene_ids) if scene_ids is not None else None
        for scene in scenes:
            if selected is not None and scene.id not in selected:
                continue
            sheet = (scene.metadata or {}).get("storyboard_sheet") or {}
            if sheet.get("image_url") and sheet.get("status") == "completed" and sheet.get("scene_fingerprint") == scene_fingerprint(scene):
                continue
            token = submission.set({"submission_id": str(batch_id), "submission_hash": f"{batch_id}:{scene.id}:{model_id}"})
            try:
                task = await submit_sheet(scene.id, model_config_id=model_id, team_id=team_id, user_id=user_id)
            finally:
                submission.reset(token)
            tasks.append(str(task.id))
    return tasks


async def submit_sheet_edit(scene_id, request, *, team_id=None, user_id=None):
    from copy import deepcopy
    from controllers.config import ai_model_config_controller, general_config_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import prepare_workflow
    from services.creation_agent.submissions import previous_submission
    from services.storyboard.sheet_history import current_sheet, sheet_revision
    from services.video_enhancement.sources import require_generation_scope
    from prompts.storyboard_sheet_edit import render_sheet_edit
    scene = await Scene.get(id=scene_id).prefetch_related('chapter__novel')
    await require_generation_scope(scene.chapter.novel_id, team_id)
    async with project_write(scene.chapter.novel_id) as db:
        prior = await previous_submission(AiTaskTypeEnum.reference_image, {'team_id': team_id, 'user_id': user_id}, db)
        if prior:
            return prior
        await scene.refresh_from_db()
        source = current_sheet(scene)
        if not source.get('image_url'):
            raise HTTPException(409, localized_message('请先生成该分镜的线稿'))
        if sheet_revision(scene) != request.expected_revision:
            raise HTTPException(409, localized_message('当前线稿已变化，请刷新后重试'))
        active = await AiTask.get_or_none(id=source.get('task_id')) if source.get('task_id') else None
        if active and active.status in {1, 2, 6}:
            raise HTTPException(409, localized_message('本镜已有线稿任务，请等待完成'))
        model_id = request.model_config_id or (active.request_params.get('model_config_id') if active else None)
        if not model_id:
            raise HTTPException(422, localized_message('请选择生图模型'))
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image, model_id, team_id=team_id)
        selection = validate_selection(config.image_model_type, clarity=None,
            aspect_ratio=scene.chapter.novel.aspect_ratio or '16:9', output_format='png', generation_count=1)
        language = await general_config_controller.get_prompt_language()
        source_prompt = (active.request_params.get('original_image_prompt') or (active.request_params.get('sheet') or {}).get('image_prompt')) if active else None
        original = source_prompt or scene.prompt or scene.description or ''
        # Preserve the source's video guidance. Editing the image does not rewrite the shot.
        sheet = {'image_prompt': render_sheet_edit(original, request.instruction, language),
                 'video_prompt': source.get('video_prompt', scene.prompt), 'video_guidance': source.get('video_guidance', '')}
        params = dict(operation='storyboard_sheet_edit', scene_id=scene.id, chapter_id=scene.chapter_id,
            novel_id=scene.chapter.novel_id, team_id=team_id, user_id=user_id, model_config_id=config.id,
            model=config.model, prompt_language=language, clarity=selection.clarity, resolution=selection.provider_size,
            aspect_ratio=selection.aspect_ratio, output_format='png', generation_count=1,
            source_sheet=deepcopy(source), original_image_prompt=original, edit_instruction=request.instruction, sheet=sheet,
            scene_fingerprint=scene_fingerprint(scene), edit_fingerprint=sheet_edit_fingerprint(scene), source_revision=request.expected_revision)
        prepared = await prepare_workflow(params)
        for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id'):
            prepared.pop(key, None)
        task = await ai_task_executor.submit(AiTaskTypeEnum.reference_image, prepared, db_connection=db)
        scene.metadata = {**(scene.metadata or {}), 'storyboard_sheet': {
            **source, 'task_id': str(task.id), 'status': 'pending', 'previous_image_url': source['image_url']}}
        await scene.save(update_fields=['metadata', 'updated_at'])
        return task


async def execute_sheet_edit(params):
    from controllers.config import ai_model_config_controller
    from services.creation_agent.operation_receipts import execute_step
    from services.reference.generator import generate_for_sora_consistency
    from services.reference.handler import _persist_generated_image
    from services.image_inputs import resolve_reference_images
    scene = await Scene.get(id=params['scene_id'], chapter__novel_id=params['novel_id']).prefetch_related('chapter')
    if sheet_edit_fingerprint(scene) != params['edit_fingerprint'] or await parent_cancelled(params):
        raise ValueError(localized_message('分镜已变化或任务已停止，请重新提交'))

    async def generate():
        await scene.refresh_from_db()
        if not sheet_task_is_current(scene, params):
            raise ValueError(localized_message('当前线稿已变化，请刷新后重试'))
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image, params['model_config_id'], team_id=params.get('team_id'))
        references = resolve_reference_images([params['source_sheet']['image_url']])
        images = await generate_for_sora_consistency({'base_traits': params['sheet']['image_prompt']},
            base_url=config.base_url, api_key=config.api_key, model=config.model, api_protocol=config.api_protocol,
            resolution=params['resolution'], aspect_ratio=params['aspect_ratio'], reference_images=references, count=1,
            prompt_language=params['prompt_language'])
        if len(images) != 1:
            raise ValueError(localized_message('故事版须返回一张图片'))
        url = await _persist_generated_image(images[0], scene.id, f'_storyboard_{params["task_id"]}')
        return {'url': url}

    generated = await execute_step(params['task_id'], 'sheet:generate', generate, external=True)
    return await execute_step(params['task_id'], 'sheet:apply',
        lambda: apply_sheet_result(scene, params, generated['url'], 1), atomic=True)


async def apply_sheet_result(scene, params, url, input_image_count):
    from uuid import uuid4
    sheet = {'task_id': str(params['task_id']), 'status': 'completed', 'image_url': url,
             'revision': str(uuid4()), 'scene_fingerprint': params['scene_fingerprint'],
             'video_prompt': params['sheet']['video_prompt'], 'video_guidance': params['sheet'].get('video_guidance', '')}
    result = {'scene_id': scene.id, 'scene_ids': [scene.id], 'images': [url], 'image_count': 1,
              'input_image_count': input_image_count, 'saved': False, 'sheet': sheet}
    async with project_write(scene.chapter.novel_id):
        current = await Scene.get_or_none(id=scene.id)
        task = await AiTask.get(id=params['task_id'])
        if (current and task.status == TaskStatusEnum.running and scene_fingerprint(current) == params['scene_fingerprint']
                and sheet_task_is_current(current, params)
                and not await parent_cancelled(params)):
            current.metadata = {**(current.metadata or {}), 'storyboard_sheet': sheet}
            await current.save(update_fields=['metadata', 'updated_at'])
            result['saved'] = True
    if not result['saved']:
        result['not_applied_reason'] = localized_message('新版线稿已保留，请在历史中查看并选择是否使用')
    return result


def sheet_task_is_current(scene, params):
    from services.storyboard.sheet_history import current_sheet
    current = current_sheet(scene)
    if current.get('task_id') != str(params['task_id']):
        return False
    if params.get('operation') == 'storyboard_sheet_edit':
        source = params['source_sheet']
        return (current.get('image_url') == source.get('image_url') and current.get('revision') == source.get('revision')
                and sheet_edit_fingerprint(scene) == params['edit_fingerprint'])
    return True


def sheet_edit_fingerprint(scene):
    from services.video_enhancement.media import digest
    return digest([scene_fingerprint(scene), (scene.metadata or {}).get('asset_variant_ids')])
