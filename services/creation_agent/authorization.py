"""Free text proposes production; only exact commands or UI actions grant execution."""

import re
from uuid import UUID, uuid5

from schemas.agent_workflow import ProductionAuthorization, ProductionIntent
from services.creation_agent.skill_execution import current_execution

INTERNAL_INPUT_KEYS = {"resolved_production_intents", "production_proposals"}


def public_run_input(value):
    return {key: item for key, item in value.items() if key not in INTERNAL_INPUT_KEYS}


# A deliberately small command vocabulary: full-message equality, not keyword
# matching. Other wording can propose a task for explicit UI confirmation.
DIRECT_COMMANDS = {
    "image": {
        "生成图片",
        "生成选中角色的图片",
        "generate image",
        "generate images",
        "generate the selected images",
    },
    "video": {
        "生成视频",
        "生成选中分镜的视频",
        "generate video",
        "generate videos",
        "generate the selected videos",
    },
    "assets": {"提取本章资产", "extract chapter assets"},
    "storyboard": {"生成本章分镜", "generate chapter storyboard"},
    "story": {"分析故事", "analyze story"},
    "compose": {"合成本章视频", "compose chapter video"},
}


def direct_operation(message: str):
    command = message.strip().casefold()
    command = re.sub(r"[。！.!]$", "", command)
    return next(
        (
            operation
            for operation, commands in DIRECT_COMMANDS.items()
            if command in commands
        ),
        None,
    )


async def resolve_production_intents(request, novel_id, user_message):
    execution = current_execution.get()
    if request.write_scope == "read_only":
        return request.model_copy(update={"production_intents": []})
    saved = user_message.run_input.get("resolved_production_intents")
    if saved is not None:
        return request.model_copy(
            update={
                "production_intents": [
                    ProductionIntent.model_validate(item) for item in saved
                ]
            }
        )
    from models.asset import Asset
    from models.scene import Scene
    from models.asset_variant import AssetVariant
    from models.remake_source import RemakeSource

    targets = []
    for target in request.targets:
        model = {"asset": Asset, "scene": Scene, "variant": AssetVariant}[target.kind]
        row = await model.get_or_none(id=target.id)
        if row:
            targets.append(
                {
                    "kind": target.kind,
                    "id": target.id,
                    "asset_id": row.asset_id if target.kind == "variant" else None,
                    "name": getattr(row, "canonical_name", None)
                    or getattr(row, "name", None)
                    or getattr(row, "description", ""),
                }
            )
    operation = direct_operation(request.message)
    specifications = []
    if operation in {"image", "video"}:
        for target in targets:
            if operation == "image" and target["kind"] in {"asset", "variant"}:
                specifications.append(
                    {
                        "operation": operation,
                        "target_id": target["asset_id"] or target["id"],
                        "variant_id": target["id"]
                        if target["kind"] == "variant"
                        else None,
                    }
                )
            elif operation == "video" and target["kind"] == "scene":
                specifications.append(
                    {"operation": operation, "target_id": target["id"]}
                )
    elif operation == "story" and request.write_scope == "project":
        specifications = [{"operation": operation, "target_id": novel_id}]
    elif (
        operation in {"assets", "storyboard", "compose"}
        and request.chapter_id
        and request.write_scope in {"chapter", "project"}
    ):
        specifications = [{"operation": operation, "target_id": request.chapter_id}]

    if specifications:
        granted = True
    else:
        # This classifier can suggest targets, but its output can never authorize
        # media calls, even if it misreads negation, quotations or hypotheticals.
        sources = await RemakeSource.filter(novel_id=novel_id).values(
            "id", "chapter_id", "episode_number", "media_status"
        )
        from models.chapter_export import ChapterExport
        exports = await ChapterExport.filter(novel_id=novel_id, parent_export_id__isnull=True,source_sha256__not_isnull=True).order_by('-id').limit(20).values('id','chapter_id','source_sha256')
        result = await execution.generate(
            "authorization",
            {
                "user_message": request.message,
                "selected_targets": targets,
                "chapter_id": request.chapter_id,
                "project_id": novel_id,
                "remake_sources": sources,
                'chapter_exports': exports,
                "write_scope": request.write_scope,
            },
            ProductionAuthorization,
        )
        specifications = [
            item.model_dump(exclude={"source_quote"})
            for item in result.intents
            if item.source_quote in request.message
        ]
        granted = False
    intents = [
        ProductionIntent(
            **item,
            request_id=uuid5(UUID(execution.params["task_id"]), f"intent:{index}"),
        )
        for index, item in enumerate(specifications)
    ]
    # Scope checks apply before presenting proposals as well as before executing.
    from services.creation_agent.intent_tools import validate_intent_scope

    checked = []
    for intent in intents:
        try:
            await validate_intent_scope(intent, request=request, novel_id=novel_id)
            if intent.operation == 'enhance_export':
                from controllers.chapter_export import chapter_exports
                from services.creation_agent.handler import authorize_run
                from schemas.video_export import ExportEnhanceIn
                ctx = await authorize_run(execution.params)
                export = await chapter_exports.get(intent.target_id, ctx)
                models = await chapter_exports.configs(ctx)
                if not models:
                    continue
                quote = await chapter_exports.quote(export, models[0].id, ctx)
                intent = intent.model_copy(update={'enhancement':ExportEnhanceIn(model_config_id=models[0].id,
                    source_sha256=quote['source_sha256'], quote_version=quote['quote_version'])})
        except ValueError:
            continue
        checked.append(intent)
    user_message.run_input = {
        **user_message.run_input,
        "resolved_production_intents": [
            item.model_dump(mode="json") for item in checked
        ]
        if granted
        else [],
        "production_proposals": [item.model_dump(mode="json") for item in checked]
        if not granted
        else [],
    }
    await user_message.save(update_fields=["run_input"])
    return request.model_copy(update={"production_intents": checked if granted else []})


async def pending_production(task_id):
    from models.creation_agent import AgentMessage

    message = await AgentMessage.get_or_none(task_id=task_id, role="user")
    if not message or not message.run_input.get("production_proposals"):
        return None
    confirmation_id = uuid5(UUID(str(task_id)), "production-confirmation")
    if await AgentMessage.filter(
        conversation_id=message.conversation_id, request_id=confirmation_id, role="user"
    ).exists():
        return None
    original = public_run_input(message.run_input)
    from models.ai_task import AiTask

    task = await AiTask.get(id=task_id)
    from utils.messages import localized_message

    intents = [
        ProductionIntent.model_validate(item)
        for item in message.run_input["production_proposals"]
    ]
    labels = []
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    from models.chapter import Chapter
    from models.novel import Novel
    from models.remake_source import RemakeSource
    from models.chapter_export import ChapterExport

    for intent in intents:
        model = {
            "image": Asset,
            "video": Scene,
            "story": Novel,
            "assets": Chapter,
            "storyboard": Chapter,
            "compose": Chapter,
            "remake": RemakeSource,
            'prepare_export': Chapter,
            'enhance_export': ChapterExport,
        }[intent.operation]
        row = await model.get_or_none(id=intent.target_id)
        label = (
            getattr(row, "canonical_name", None)
            or getattr(row, "name", None)
            or getattr(row, "description", None)
            or getattr(row, "original_filename", None)
            or str(intent.target_id)
        )
        if intent.variant_id:
            variant = await AssetVariant.get_or_none(
                id=intent.variant_id, asset_id=intent.target_id
            )
            label += " / " + (variant.name if variant else str(intent.variant_id))
        if intent.operation == 'enhance_export' and intent.enhancement:
            from controllers.chapter_export import chapter_exports
            from services.creation_agent.handler import authorize_run
            try:
                ctx = await authorize_run(task.request_params)
                quote = await chapter_exports.quote(row, intent.enhancement.model_config_id, ctx)
                if quote['quote_version'] == intent.enhancement.quote_version:
                    label += f" · {quote['config_snapshot']['name']} · 1080p · ¥{quote['amount']}"
                else:
                    label += ' · ' + localized_message('来源或报价已变化，请重新确认')
            except Exception:
                label += ' · ' + localized_message('请先核对高清导出的来源与费用')
        labels.append({"operation": intent.operation, "target_label": label})
    return {
        "confirmation_request_id": str(
            uuid5(UUID(str(task_id)), "production-confirmation")
        ),
        "message": localized_message(
            "确认执行所列生成任务",
            _language=task.request_params.get("prompt_language", "en"),
        ),
        "labels": labels,
        "intents": message.run_input["production_proposals"],
        "chapter_id": original.get("chapter_id"),
        "targets": original.get("targets", []),
        "write_scope": original.get("write_scope", "selected"),
        "model_config_id": original.get("model_config_id"),
    }
