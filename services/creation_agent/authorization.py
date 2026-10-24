"""Resolve only this turn's explicit production request, never historical instructions."""

from utils.messages import localized_message

from uuid import UUID, uuid5
from schemas.agent_workflow import ProductionAuthorization, ProductionIntent
from services.creation_agent.skill_execution import current_execution


async def resolve_production_intents(request, novel_id, user_message):
    execution = current_execution.get()
    if request.write_scope == "read_only":
        return request
    saved = user_message.run_input.get("resolved_production_intents")
    if saved is not None:
        return request.model_copy(
            update={
                "production_intents": [
                    ProductionIntent.model_validate(item) for item in saved
                ]
            }
        )
    # Selected object names are fact data; no manuscript/history enters this call.
    from models.asset import Asset
    from models.scene import Scene
    from models.asset_variant import AssetVariant

    targets = []
    for target in request.targets:
        model = {"asset": Asset, "scene": Scene, "variant": AssetVariant}[target.kind]
        row = await model.get_or_none(id=target.id)
        if row:
            targets.append(
                {
                    "kind": target.kind,
                    "asset_id": row.asset_id if target.kind == "variant" else None,
                    "id": target.id,
                    "name": getattr(row, "canonical_name", None)
                    or getattr(row, "name", None)
                    or getattr(row, "description", ""),
                }
            )
    from models.remake_source import RemakeSource
    remake_sources = await RemakeSource.filter(novel_id=novel_id).values("id", "chapter_id", "episode_number", "media_status")
    result = await execution.generate(
        "authorization",
        {
            "user_message": request.message,
            "selected_targets": targets,
            "chapter_id": request.chapter_id,
            "project_id": novel_id,
            "remake_sources": remake_sources,
            "write_scope": request.write_scope,
        },
        ProductionAuthorization,
    )
    grants = []
    for index, item in enumerate(result.intents):
        if item.source_quote not in request.message:
            raise ValueError(localized_message("生成授权必须逐字来自本轮用户请求"))
        grants.append(
            ProductionIntent(
                operation=item.operation,
                target_id=item.target_id,
                variant_id=item.variant_id,
                request_id=uuid5(
                    UUID(execution.params["task_id"]),
                    f"intent:{index}:{item.operation}:{item.target_id}",
                ),
            )
        )
    user_message.run_input = {
        **user_message.run_input,
        "resolved_production_intents": [
            item.model_dump(mode="json") for item in grants
        ],
    }
    await user_message.save(update_fields=["run_input"])
    return request.model_copy(update={"production_intents": grants})
