"""Persist video reservations before assistant execution; keep the public Video response."""

from utils.messages import localized_message

from fastapi import HTTPException
from models.ai_task import AiTask
from models.scene import Scene
from models.video import Video
from services.creation_objects import project_write as creation_write
from services.creation_agent.skill_execution import prepare_workflow
from utils.enums import AiTaskTypeEnum


async def submit_video(req, *, media_base_url="", team_id=None, user_id=None):
    from controllers.config import ai_model_config_controller
    from services.video import get_record_model_type
    from services.language import configured_language
    from services.balance import ensure_solvent

    from services.creation_agent.submissions import submission

    envelope = submission.get() or {}
    if req.request_id is None and envelope.get("submission_id"):
        req = req.model_copy(update={"request_id": envelope["submission_id"]})
    scene = await Scene.get_or_none(id=req.scene_id).prefetch_related("chapter")
    if scene is None:
        raise HTTPException(404, localized_message("分镜不存在"))
    await ensure_solvent(team_id, user_id)
    auto_snapshot = None
    if req.auto_enhancement:
        from services.video_enhancement.automatic import enhancement_snapshot
        from services.video_enhancement.sources import require_generation_scope
        await require_generation_scope(scene.chapter.novel_id, team_id)
        auto_snapshot = await enhancement_snapshot(req.auto_enhancement, team_id)
    config = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.video.value, req.model_config_id, team_id=team_id
    )
    from services.video.capabilities import validate_selection

    selection = validate_selection(
        config.video_model_type,
        api_protocol=config.api_protocol,
        generation_mode=req.generation_mode,
        resolution=req.resolution,
        aspect_ratio=req.aspect_ratio,
        duration=req.duration if req.duration is not None else int(scene.duration or 6),
        output_format=req.output_format,
        generate_audio=req.generate_audio,
        return_last_frame=req.return_last_frame,
    )
    if req.auto_enhancement:
        from services.video_enhancement.contract import RESOLUTION_SHORT_SIDE, resolution_short_side
        if (resolution_short_side(selection.resolution) or 0) >= RESOLUTION_SHORT_SIDE[req.auto_enhancement.resolution]:
            raise HTTPException(422, localized_message('自动高清化目标必须高于生成分辨率'))
    if req.generation_mode == "keyframes" and (
        not req.first_frame_url or not req.last_frame_url or req.reference_media
    ):
        raise HTTPException(
            400, localized_message("首尾帧模式需要两张关键帧且不能使用参考素材")
        )
    params = await prepare_workflow(
        {
            "novel_id": scene.chapter.novel_id,
            "chapter_id": scene.chapter_id,
            "team_id": team_id,
            "user_id": user_id,
            "model_config_id": config.id,
            "operation": "video",
            "video_request": req.model_dump(mode="json"),
            "media_base_url": media_base_url,
            "prompt_language": await configured_language(),
            **({'auto_enhancement_snapshot': auto_snapshot} if auto_snapshot else {}),
        }
    )
    async with creation_write(scene.chapter.novel_id) as connection:
        from services.creation_agent.submissions import (
            previous_submission,
            submit_once,
            bind_submission,
        )

        previous = await previous_submission(4, params, connection)
        if previous:
            return await Video.get(id=previous.request_params["video_id"]).using_db(
                connection
            )
        for video in (
            await Video.filter(scene_id=scene.id).using_db(connection).order_by("-id")
        ):
            metadata = video.metadata or {}
            if req.request_id and metadata.get("request_id") == str(req.request_id):
                if metadata.get("video_request") != params["video_request"]:
                    raise HTTPException(
                        409, localized_message("同一请求标识不能对应不同内容")
                    )
                await bind_submission(
                    await AiTask.get(id=metadata["agent_run_id"]), params
                )
                return video
            if video.status in {1, 2, 6} and metadata.get("agent_run_id"):
                await bind_submission(
                    await AiTask.get(id=metadata["agent_run_id"]), params
                )
                return video

        async def create(connection):
            task = await AiTask.create(
                task_type=AiTaskTypeEnum.video.value,
                status=6,
                request_params=params,
                using_db=connection,
            )
            video = await Video.create(
                scene=scene,
                model_type=get_record_model_type(config).value,
                status=6,
                metadata={
                    "agent_run_id": str(task.id),
                    "request_id": str(req.request_id) if req.request_id else None,
                    "video_request": params["video_request"],
                    "novel_id": scene.chapter.novel_id,
                    "model_config_id": config.id,
                    "team_id": team_id,
                    "user_id": user_id,
                },
                using_db=connection,
            )
            task.request_params = {**params, "video_id": video.id}
            await task.save(using_db=connection, update_fields=["request_params"])
            if req.auto_enhancement:
                from models.agent_operation import AgentOperation
                from services.video_enhancement.automatic import KEY
                await AgentOperation.create(task=task, key=KEY, result={'stage': 'waiting_video'}, using_db=connection)
                video.metadata = {**video.metadata, 'auto_enhancement': {'stage': 'waiting_video'}}
                await video.save(using_db=connection, update_fields=['metadata'])
            return task

        task = await submit_once(4, params, create)
        video = await Video.get(id=task.request_params["video_id"]).using_db(connection)
    return video


class VideoProductionHandler:
    def timeout_seconds(self, params):
        return 600

    async def execute(self, params):
        from controllers.video import video_controller
        from schemas.video import VideoGenerateRequest
        from services.creation_agent.skill_execution import current_execution
        from services.creation_agent.operation_receipts import execute_step
        from schemas.agent_workflow import CompletePrompt

        execution = current_execution.get()
        from models.agent_operation import AgentOperation
        from services.creation_agent.waiting import WaitingForMedia
        completed = await AgentOperation.get_or_none(task_id=params['task_id'], key='media:video', state='completed')
        if completed:
            raise WaitingForMedia(completed.result)
        req = VideoGenerateRequest.model_validate(params["video_request"])
        scene = await Scene.get(id=req.scene_id)
        if params.get('creation_plan_id'):
            from services.creation_agent.media_preparation import prepare_planned_media
            await prepare_planned_media(execution, kind='scene', target=scene)
        if not (scene.prompt or "").strip():
            generated = await execution.generate(
                "video",
                {
                    "description": scene.description,
                    "structure": scene.prompt_params,
                    "duration": scene.duration,
                },
                CompletePrompt,
            )
            async with creation_write(params["novel_id"]):
                await scene.refresh_from_db()
                if not (scene.prompt or "").strip():
                    scene.prompt = generated.prompt
                    await scene.save(update_fields=["prompt", "updated_at"])

        async def invoke():
            await execution.before_request()
            if params.get('creation_plan_id'):
                from services.creation_agent.media_preparation import validate_prepared_media
                await validate_prepared_media(execution, scene)
            video = await video_controller._submit_generation(
                req,
                media_base_url=params.get("media_base_url", ""),
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
                reserved_video_id=params["video_id"],
            )
            return {"video_id": video.id, "external_task_id": video.external_task_id}

        result = await execute_step(
            params["task_id"], "media:video", invoke, external=True
        )
        from services.creation_agent.waiting import WaitingForMedia

        raise WaitingForMedia(result)
