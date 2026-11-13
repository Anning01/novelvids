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
            sheet=sheet_for(scene, language), scene_fingerprint=scene_fingerprint(scene))
        previous = await previous_submission(AiTaskTypeEnum.reference_image, params, db)
        if previous:
            return previous
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.reference_image, status__in=[TaskStatusEnum.pending, TaskStatusEnum.running, TaskStatusEnum.queued]).using_db(db):
            if (task.request_params or {}).get('scene_id') == scene.id and (task.request_params or {}).get('operation') == 'storyboard_sheet':
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
    from models.asset_variant import AssetVariant
    execution = current_execution.get()
    if execution:
        await execution.before_request()
    if await parent_cancelled(params):
        raise ValueError(localized_message('任务已停止'))
    scene = await Scene.get(id=params['scene_id'], chapter__novel_id=params['novel_id']).prefetch_related('chapter__novel', 'assets')
    if not scene.chapter.novel.storyboard_enabled or scene_fingerprint(scene) != params['scene_fingerprint']:
        raise ValueError(localized_message('分镜或故事版设置已修改，请重新生成'))
    config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image, params['model_config_id'], team_id=params.get('team_id'))
    variants = {row.asset_id: row for row in await AssetVariant.filter(id__in=list((scene.metadata or {}).get('asset_variant_ids', {}).values()))}
    references, identities = [], []
    for asset in await Asset.filter(scenes__id=scene.id):
        variant = variants.get(asset.id)
        images = variant.images if variant else []
        identities.append({'name': asset.canonical_name, 'variant': variant.name if variant else None,
            'visual_description': variant.base_traits if variant else asset.base_traits})
        image = next((item.get('url') if isinstance(item, dict) else item for item in images if item), None) or asset.main_image
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
    result = {'scene_id': scene.id, 'images': [url], 'image_count': 1, 'input_image_count': len(references), 'saved': False}
    async with project_write(scene.chapter.novel_id):
        current = await Scene.get_or_none(id=scene.id)
        task = await AiTask.get(id=params['task_id'])
        if current and task.status == TaskStatusEnum.running and scene_fingerprint(current) == params['scene_fingerprint'] and not await parent_cancelled(params):
            current.metadata = {**(current.metadata or {}), 'storyboard_sheet': {
                'task_id': str(task.id), 'status': 'completed', 'image_url': url, 'scene_fingerprint': params['scene_fingerprint'],
                'video_prompt': params['sheet']['video_prompt'], 'video_guidance': params['sheet'].get('video_guidance', '')}}
            await current.save(update_fields=['metadata', 'updated_at'])
            result['saved'] = True
    return result
