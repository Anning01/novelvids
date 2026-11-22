"""Queue and apply a chapter's model-specific prompt drafts independently of its editor."""
import asyncio
import json
import logging

from fastapi import HTTPException
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.chapter import Chapter
from models.scene import Scene
from prompts.video_optimizer import validate_asset_markers
from schemas.scene import ScenePromptOptimization
from services.ai_task_executor import ai_task_executor
from services.creation_agent.handler import authorize_run
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.skill_execution import current_execution, prepare_workflow, require_workflow_model
from services.creation_agent.submissions import previous_submission, submission
from services.creation_objects import project_write
from services.storyboard.prompt_optimization import resolve_prompt_optimizer, submit_prompt_optimization
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message, public_generation_error


def batch_key(chapter_id, ctx):
    return f'prompt-batch:{chapter_id}:{ctx.team_id}:{ctx.user.id if ctx.user else None}'


async def latest_batch(chapter_id, ctx):
    row = await AgentOperation.filter(key=batch_key(chapter_id, ctx)).order_by('-id').select_related('task').first()
    return row.task if row else None


def scene_version(scene):
    # Submitting a single optimization records its task ID in prompt_params.
    context = dict(scene.prompt_params or {})
    context.pop('video_prompt_tasks', None)
    return fingerprint([scene.prompt, scene.description, scene.duration, scene.metadata, context,
                        sorted(asset.id for asset in scene.assets)])


async def submit_batch(chapter_id, body, ctx):
    chapter = await Chapter.get(id=chapter_id)
    model, optimizer = await resolve_prompt_optimizer(body.shots[0].model_config_id, ctx)
    params = await prepare_workflow(dict(video_optimizer=optimizer, operation='optimize_chapter_prompts', chapter_id=chapter_id,
        novel_id=chapter.novel_id, team_id=ctx.team_id, user_id=ctx.user.id if ctx.user else None))
    async with project_write(chapter.novel_id) as db:
        previous = await previous_submission(AiTaskTypeEnum.prompt_optimization, params, db)
        if previous:
            return previous
        active = await latest_batch(chapter_id, ctx)
        if active and active.status in (1, 2, 6):
            if active.request_params['video_model_config_id'] != model.id:
                raise HTTPException(409, localized_message('请等待当前任务完成后再切换模型'))
            return active
        scenes = await Scene.filter(chapter_id=chapter_id, id__in=[s.scene_id for s in body.shots]).prefetch_related('assets')
        by_id = {scene.id: scene for scene in scenes}
        if len(scenes) != len(body.shots):
            raise HTTPException(422, localized_message('分镜不存在'))
        shots = []
        for shot in body.shots:
            scene = by_id[shot.scene_id]
            if scene.prompt != shot.expected_prompt:
                raise HTTPException(409, localized_message('提示词已被其他操作修改，本地草稿未覆盖新内容，请重新读取后核对'))
            shots.append({**shot.model_dump(exclude={'expected_prompt'}), 'version': scene_version(scene)})
        task = await ai_task_executor.submit(AiTaskTypeEnum.prompt_optimization,
            {**params, 'prompt_batch_shots': shots, 'total': len(shots), 'video_model_config_id': model.id,
             'model_type': model.video_model_type}, db_connection=db)
        await AgentOperation.create(task=task, key=batch_key(chapter_id, ctx), state='completed', using_db=db)
        return task


async def unchanged_scene(chapter_id, shot):
    scene = await Scene.filter(id=shot['scene_id'], chapter_id=chapter_id).prefetch_related('assets').first()
    if not scene or scene_version(scene) != shot['version']:
        raise ValueError(localized_message('提示词已被其他操作修改，本地草稿未覆盖新内容，请重新读取后核对'))
    return scene


async def apply_draft(params, shot, model_type, prompt):
    from services.video.reference_media import reference_mention_syntax
    from services.storyboard.blocking_reference import BLOCKING_ID, blocking_source
    from prompts.storyboard_sheet_binding import bind_blocking, blocking_rules, sheet_binding_rules

    async with project_write(params['novel_id']):
        scene = await unchanged_scene(params['chapter_id'], shot)
        metadata = dict(scene.metadata or {})
        # Keep the same version identity as the editor's JSON.stringify(optimizationInput).
        facts = {k: shot[k] for k in ('generic_prompt', 'duration', 'aspect_ratio', 'generation_mode', 'submitted_media')}
        versions = dict(metadata.get('video_prompt_versions') or {})
        versions[model_type] = {'prompt': prompt, 'input': json.dumps(facts, ensure_ascii=False, separators=(',', ':'))}
        metadata.update(video_prompt_versions=versions, video_prompt_model=model_type, generic_video_prompt=shot['generic_prompt'])
        if shot['generation_mode'] == 'reference':
            language = metadata.get('prompt_language', params['prompt_language'])
            sheet = metadata.get('storyboard_sheet') or {}
            if not metadata.get('storyboard_sheet_excluded') and (sheet.get('image_url') or sheet.get('previous_image_url')):
                rules = sheet_binding_rules(sheet, language)
                prompt = bind_blocking(prompt, rules.get(model_type, rules['general']), reference_mention_syntax('image', 'novelvids:storyboard-sheet'))
            if blocking_source(scene.id, metadata, scene.prompt_params):
                rules = blocking_rules(language)
                prompt = bind_blocking(prompt, rules.get(model_type, rules['general']), reference_mention_syntax('image', BLOCKING_ID))
        scene.prompt, scene.metadata = prompt, metadata
        await scene.save(update_fields=['prompt', 'metadata', 'updated_at'])
        return {'scene_id': scene.id}


async def run_batch(params):
    from controllers.config import ai_model_config_controller
    execution = current_execution.get()
    ctx = await authorize_run(params)
    shots = params['prompt_batch_shots']
    model = await ai_model_config_controller.get_active(AiTaskTypeEnum.video, shots[0]['model_config_id'], team_id=ctx.team_id)
    assistant, _ = await require_workflow_model(params)
    slots = asyncio.Semaphore(max(1, assistant.concurrency))
    completed, failed = [], {}
    progress_lock = asyncio.Lock()

    def progress():
        return {'total': len(shots), 'saved_scene_ids': list(completed), 'failed_scene_ids': list(failed),
                'errors': [{'scene_id': key, 'message': message} for key, message in failed.items()]}

    async def optimize(shot):
        scene_id = shot['scene_id']

        async def work():
            await execution.before_request()
            # A replay may have already committed this scene before recording progress.
            applied = await AgentOperation.get_or_none(task_id=params['task_id'], key=f'apply-prompt:{scene_id}', state='completed')
            if applied:
                return applied.result
            await unchanged_scene(params['chapter_id'], shot)
            prompt = shot['cached_prompt']
            if not prompt:
                # Single-shot receipts reuse completed model output after a failed save.
                task = await submit_prompt_optimization(scene_id, ScenePromptOptimization.model_validate(shot), ctx)
                await ai_task_executor.run(task)
                await task.refresh_from_db()
                while task.status in (1, 2, 6):
                    await asyncio.sleep(1)
                    await task.refresh_from_db()
                if task.status != 3:
                    raise ValueError(task.error_message or localized_message('提示词优化失败'))
                result = task.response_data
                if result['scene_id'] != scene_id or result['model_type'] != model.video_model_type:
                    raise ValueError(localized_message('模型未返回提示词'))
                prompt = result['prompt']
            validate_asset_markers(prompt, shot['generic_prompt'])
            await execution.before_request()
            return await execute_step(params['task_id'], f'apply-prompt:{scene_id}',
                lambda: apply_draft(params, shot, model.video_model_type, prompt), atomic=True)

        async with slots:
            try:
                await work()
                completed.append(scene_id)
            except (ValueError, HTTPException) as error:
                failed[scene_id] = public_generation_error(str(getattr(error, 'detail', error)))
            except Exception as error:
                logging.getLogger(__name__).warning('Prompt batch shot failed: task=%s scene=%s error=%s',
                    params['task_id'], scene_id, type(error).__name__)
                failed[scene_id] = localized_message('本次生成未完成，可以重新生成')
            async with progress_lock:
                await AiTask.filter(id=params['task_id'], status=2).update(response_data=progress(),
                    progress=(len(completed) + len(failed)) * 100 // len(shots))

    token = submission.set(None)
    try:
        await asyncio.gather(*(optimize(shot) for shot in shots))
    finally:
        submission.reset(token)
    return progress()
