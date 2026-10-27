"""Button tasks share skill execution, private conversations and durable receipts."""

from utils.messages import localized_message

import hashlib
from models.ai_task import AiTask
from models.creation_agent import AgentConversation, AgentMessage
from services.creation_agent.skill_execution import (
    SkillExecution,
    current_execution,
    require_agent,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

SKILLS = {1: "assets", 2: "image", 3: "storyboard", 4: "video", 5: "story", 6: "remake", 8: "video"}


async def conversation_for_task(task):
    message = await AgentMessage.get_or_none(task_id=task.id, role="assistant")
    if message:
        return message
    params = task.request_params
    chosen, _ = await require_agent(
        params.get("team_id"), params["assistant_model_config_id"]
    )
    conversation = await AgentConversation.create(
        novel_id=params["novel_id"],
        created_by=params.get("user_id"),
        team_id=params.get("team_id"),
    )
    digest = hashlib.sha256(str(task.id).encode()).hexdigest()
    operation = params.get("operation") or SKILLS.get(task.task_type, "editing")
    labels = {
        "image": ("生成图片", "Generate image"),
        "assets": ("提取资产", "Extract assets"),
        "storyboard": ("生成分镜", "Generate storyboard"),
        "story": ("分析故事", "Analyze story"),
        "remake": ("重制视频", "Analyze source video"),
        "video": ("生成视频", "Generate video"),
        "compose": ("合成章节", "Compose episode"),
        "prepare_export": ("准备章节成片", "Prepare episode export"),
        "enhance_export": ("生成高清成片", "Enhance episode export"),
    }
    label = labels.get(operation, ("创作任务", "Creation task"))[
        0 if params.get("prompt_language") == "zh" else 1
    ]
    targets = []
    target = None
    if params.get("variant_id"):
        from models.asset_variant import AssetVariant

        target = await AssetVariant.get_or_none(
            id=params["variant_id"], asset_id=params.get("asset_id")
        )
        kind = "variant"
    elif params.get("asset_id"):
        from models.asset import Asset

        target = await Asset.get_or_none(
            id=params["asset_id"], novel_id=params["novel_id"]
        )
        kind = "asset"
    elif params.get("video_request", {}).get("scene_id"):
        from models.scene import Scene

        target = await Scene.get_or_none(
            id=params["video_request"]["scene_id"], chapter__novel_id=params["novel_id"]
        )
        kind = "scene"
    if target:
        targets = [{"kind": kind, "id": target.id}]
        label += " · " + (
            getattr(target, "canonical_name", None)
            or getattr(target, "name", None)
            or getattr(target, "description", None)
            or str(target.id)
        )
    await AgentMessage.create(
        conversation=conversation,
        task=task,
        request_id=task.id,
        request_hash=digest,
        role="user",
        content=label,
        run_input={
            "request_id": str(task.id),
            "message": label,
            "chapter_id": params.get("chapter_id"),
            "targets": targets,
            "write_scope": "selected"
            if targets
            else "chapter"
            if params.get("chapter_id")
            else "project",
        },
    )
    message = await AgentMessage.create(
        conversation=conversation,
        task=task,
        request_id=task.id,
        request_hash=digest,
        role="assistant",
        model_snapshot={
            "id": chosen.id,
            "name": chosen.name,
            "model": chosen.model,
            "scope": chosen.scope,
            "pricing": chosen.pricing,
        },
    )
    await AgentConversation.filter(id=conversation.id).update(active_task_id=task.id)
    return message


async def run_production(task, handler):
    from services.creation_agent.handler import authorize_run

    params = dict(task.request_params)

    async def before_request():
        ctx = await authorize_run(params)
        if params.get('operation') in {'prepare_export', 'enhance_export'}:
            from services.video_enhancement.sources import require_generation_scope
            await require_generation_scope(params['novel_id'], ctx.team_id)
        from services.balance import ensure_solvent

        await ensure_solvent(params.get("team_id"), params.get("user_id"))
        await require_agent(params.get("team_id"), params["assistant_model_config_id"])
        if not await AiTask.filter(
            id=task.id, status=TaskStatusEnum.running.value
        ).exists():
            raise ValueError(localized_message("任务已取消或结束"))

    await before_request()
    message = await conversation_for_task(task)
    await AiTask.filter(id=task.id).update(
        request_params={
            **task.request_params,
            "conversation_id": message.conversation_id,
        }
    )
    # Resolve credentials only at execution; never embed new secrets in task data.
    config = None
    if params.get("model_config_id"):
        from controllers.config import ai_model_config_controller

        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.creation_agent.value
            if task.task_type in {1, 3}
            else task.task_type,
            params["model_config_id"],
            team_id=params.get("team_id"),
        )
    if config:
        params.update(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            supports_json_output=config.supports_json_output,
        )
    params["task_id"] = str(task.id)
    execution = SkillExecution(
        {
            key: value
            for key, value in params.items()
            if key not in {"api_key", "base_url"}
        },
        message,
        before_request,
    )
    from utils.prompt_language import skill_workflow

    mode_token = skill_workflow.set(True)
    token = current_execution.set(execution)
    try:
        if task.task_type == AiTaskTypeEnum.reference_image.value:
            from services.creation_agent.media_execution import run_image_handler

            result = await run_image_handler(handler, params)
        else:
            result = await handler.execute(params)
        result = {
            **result,
            "conversation_id": message.conversation_id,
            "agent_run_id": str(task.id),
        }
        return result
    finally:
        current_execution.reset(token)
        skill_workflow.reset(mode_token)
        await AgentConversation.filter(
            id=message.conversation_id, active_task_id=task.id
        ).update(active_task_id=None)


async def finish_production_message(task):
    if (
        task.request_params.get("workflow_version") != "agent-skills-v1"
        or task.task_type == 7
    ):
        return
    if task.request_params.get("operation") == "video" and task.status in {4, 5}:
        from models.video import Video

        video = await Video.get_or_none(id=task.request_params.get("video_id"))
        if video and video.status == 6 and not video.external_task_id:
            await Video.filter(id=video.id, status=6).update(
                status=task.status,
                metadata={
                    **video.metadata,
                    "error": task.error_message,
                    "stage": task.stage,
                },
            )
    message = await AgentMessage.get_or_none(task_id=task.id, role="assistant")
    if message is None:
        return
    english = task.request_params.get("prompt_language", "en") == "en"
    labels = {
        3: ("已完成", "Completed"),
        4: ("任务未完成", "Task failed"),
        5: ("后续步骤已停止", "Further steps stopped"),
    }
    text = labels.get(task.status, ("处理中", "Processing"))[int(english)]
    await AgentMessage.filter(id=message.id).update(
        content=text,
        events=[
            {
                "type": "RUN_FINISHED",
                "runId": str(task.id),
                "threadId": str(message.conversation_id),
            }
        ],
    )
    await AgentConversation.filter(
        id=message.conversation_id, active_task_id=task.id
    ).update(active_task_id=None)
