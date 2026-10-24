"""User-declared production scopes are immutable; tools cannot grant themselves access."""

from utils.messages import localized_message

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.scene import Scene
from models.remake_source import RemakeSource
from schemas.agent_workflow import ProductionIntent
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.operation_receipts import execute_step


async def submit_intent(intent: ProductionIntent, *, request, novel_id: int):
    execution = current_execution.get()
    if execution is None:
        raise ValueError(localized_message("当前运行没有生成授权"))
    grants = request.production_intents
    if intent.model_dump(mode="json") not in [
        grant.model_dump(mode="json") for grant in grants
    ]:
        raise ValueError(localized_message("仅能执行用户本轮明确选择的生成操作"))
    await execution.before_request()
    await validate_intent_scope(intent, request=request, novel_id=novel_id)
    params = execution.params

    async def submit():
        if intent.operation == "image":
            from controllers.asset import asset_controller

            task = await asset_controller.reference(
                intent.target_id,
                media_model_config_id=intent.media_model_config_id,
                variant_id=intent.variant_id,
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
        elif intent.operation == "assets":
            from controllers.chapter import chapter_controller

            task = await chapter_controller.extract(
                intent.target_id,
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
        elif intent.operation == "storyboard":
            from controllers.scene import scene_controller

            task = await scene_controller.generate(
                intent.target_id,
                replace_existing=intent.replace_existing,
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
        elif intent.operation == "story":
            from controllers.novel import novel_controller

            task = await novel_controller.analyze(
                intent.target_id,
                include_cover=False,
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
        elif intent.operation == "remake":
            from models.ai_task import AiTask
            from services.remake.projects import remake_project_service

            source = await RemakeSource.get(id=intent.target_id)
            task = await AiTask.get_or_none(id=source.analysis_task_id)
            if task is None or task.status not in {1, 2, 6}:
                result = await remake_project_service.retry(
                    source.id,
                    team_id=params.get("team_id"),
                    user_id=params.get("user_id"),
                )
                task = await AiTask.get(id=result["task_id"])
        elif intent.operation == "video":
            model_id = intent.media_model_config_id
            if model_id is None:
                from models.novel import Novel

                scene = await Scene.get(id=intent.target_id)
                metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
                workbench = (
                    metadata.get("workbench")
                    if isinstance(metadata.get("workbench"), dict)
                    else {}
                )
                model_id = (
                    metadata.get("video_model_config_id")
                    or workbench.get("modelConfigId")
                    or (await Novel.get(id=novel_id)).video_model_config_id
                )
            if not model_id:
                raise ValueError(localized_message("请选择视频模型"))
            from controllers.video import video_controller
            from schemas.video import VideoGenerateRequest

            video = await video_controller.generate(
                VideoGenerateRequest(
                    scene_id=intent.target_id,
                    model_config_id=model_id,
                    request_id=intent.request_id,
                    **(
                        intent.video_options.model_dump()
                        if intent.video_options
                        else {}
                    ),
                ),
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
            from models.ai_task import AiTask

            task = await AiTask.get(id=video.metadata["agent_run_id"])
        else:
            from services.creation_agent.composition import submit_composition

            task = await submit_composition(
                intent.target_id,
                team_id=params.get("team_id"),
                user_id=params.get("user_id"),
            )
        return {"task_id": str(task.id), "status": "submitted"}

    return await execute_step(
        params["task_id"], "submit:" + str(intent.request_id), submit, atomic=True
    )


async def validate_intent_scope(intent, *, request, novel_id):
    model = {
        "image": Asset,
        "story": None,
        "assets": Chapter,
        "storyboard": Chapter,
        "video": Scene,
        "compose": Chapter,
        "remake": RemakeSource,
    }[intent.operation]
    if model is None:
        belongs = intent.target_id == novel_id
    elif model is Scene:
        belongs = await Scene.filter(
            id=intent.target_id, chapter__novel_id=novel_id
        ).exists()
    else:
        belongs = await model.filter(id=intent.target_id, novel_id=novel_id).exists()
    if not belongs:
        raise ValueError(localized_message("生成目标不属于当前项目"))
    if (
        intent.variant_id is not None
        and not await AssetVariant.filter(
            id=intent.variant_id, asset_id=intent.target_id
        ).exists()
    ):
        raise ValueError(localized_message("资产形态不属于生成目标"))
    request_scope = request.write_scope
    if request_scope == "read_only":
        raise ValueError(localized_message("只读请求不能生成"))
    if request_scope == "selected":
        kind = (
            "asset"
            if intent.operation == "image"
            else "scene"
            if intent.operation == "video"
            else None
        )
        if not any(
            target.kind == ("variant" if intent.variant_id else kind)
            and target.id == (intent.variant_id or intent.target_id)
            for target in request.targets
        ):
            raise ValueError(localized_message("生成目标不在选中范围内"))
    if request_scope == "chapter":
        if model is Chapter and intent.target_id != request.chapter_id:
            raise ValueError(localized_message("目标不在当前章节"))
        if (
            model is Scene
            and not await Scene.filter(
                id=intent.target_id, chapter_id=request.chapter_id
            ).exists()
        ):
            raise ValueError(localized_message("目标不在当前章节"))
        if (
            model is RemakeSource
            and not await RemakeSource.filter(
                id=intent.target_id, chapter_id=request.chapter_id
            ).exists()
        ):
            raise ValueError(localized_message("目标不在当前章节"))
        if model is None:
            raise ValueError(localized_message("故事分析需要项目范围"))
        if model is Asset:
            asset = await Asset.get(id=intent.target_id)
            chapter = await Chapter.get_or_none(
                id=request.chapter_id, novel_id=novel_id
            )
            if not chapter or (
                not asset.is_global
                and chapter.number not in (asset.source_chapters or [])
            ):
                raise ValueError(localized_message("目标不在当前章节"))
