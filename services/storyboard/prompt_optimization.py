"""Optimize the selected shot's text with the selected video model's installed skill."""
from pathlib import Path

from fastapi import HTTPException

from config import settings
from controllers.config import ai_model_config_controller
from models.ai_task import AiTask
from models.scene import Scene
from schemas.agent_workflow import CompletePrompt
from services.ai_task_executor import BaseTaskHandler, ai_task_executor
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.skill_execution import current_execution, prepare_workflow
from services.creation_agent.video_optimizer import optimizer_instructions, snapshot_optimizer
from services.creation_objects import project_write
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.messages import localized_message


async def submit_prompt_optimization(scene_id, body, ctx):
    scene = await Scene.get_or_none(id=scene_id).select_related("chapter")
    if not scene:
        raise HTTPException(404, localized_message("分镜不存在"))
    model = await ai_model_config_controller.get_active(AiTaskTypeEnum.video, body.model_config_id, team_id=ctx.team_id)
    optimizer = snapshot_optimizer(model.video_model_type, Path(settings.CREATION_AGENT_OPTIONAL_SKILLS_PATH))
    if optimizer["mode"] != "optimize":
        raise HTTPException(422, localized_message("当前视频模型尚未安装提示词优化技能"))
    facts = body.model_dump(exclude={"model_config_id"})
    facts["selected_model_type"] = model.video_model_type
    facts["asset_reference_policy"] = "preserve-markers-v1"
    from services.storyboard.blocking_reference import blocking_source
    from prompts.storyboard_sheet_binding import blocking_rules
    if body.generation_mode == "reference" and blocking_source(scene.id, scene.metadata, scene.prompt_params):
        rules = blocking_rules((scene.metadata or {}).get("prompt_language", "zh"))
        facts["blocking_guidance"] = rules.get(model.video_model_type, rules["general"])["line"].replace("{image}", localized_message("空间定位图"))
    params = await prepare_workflow(dict(operation="optimize_video_prompt", novel_id=scene.chapter.novel_id,
        chapter_id=scene.chapter_id, scene_id=scene.id, team_id=ctx.team_id, user_id=ctx.user.id if ctx.user else None,
        video_optimizer=optimizer, prompt_inputs=facts))
    key = fingerprint([facts, optimizer, params["prompt_language"], params["team_id"], params["user_id"]])
    async with project_write(scene.chapter.novel_id) as db:
        await scene.refresh_from_db(using_db=db)
        data = dict(scene.prompt_params or {})
        tasks = dict(data.get("video_prompt_tasks") or {})
        prior = tasks.get(model.video_model_type, {})
        if prior.get("key") == key:
            task = await AiTask.get_or_none(id=prior["id"]).using_db(db)
            if task and task.status not in {TaskStatusEnum.cancelled, TaskStatusEnum.failed}:
                return task
        task = await ai_task_executor.submit(AiTaskTypeEnum.prompt_optimization, params, db_connection=db)
        tasks[model.video_model_type] = {"id": str(task.id), "key": key}
        scene.prompt_params = {**data, "video_prompt_tasks": tasks}
        await scene.save(update_fields=["prompt_params"], using_db=db)
        return task


class PromptOptimizationHandler(BaseTaskHandler):
    async def execute(self, params):
        optimizer = params["video_optimizer"]
        from prompts.video_optimizer import validate_asset_markers
        async def validate(draft):
            validate_asset_markers(draft.prompt, params['prompt_inputs']['generic_prompt'])
        draft = await current_execution.get().generate("video", params["prompt_inputs"], CompletePrompt,
            additional_instructions=optimizer_instructions(optimizer), output_validator=validate)
        await validate(draft)
        if not draft.prompt.strip():
            raise ValueError(localized_message("模型未返回提示词"))
        return {"scene_id": params["scene_id"], "model_type": optimizer["model_type"], "prompt": draft.prompt}
