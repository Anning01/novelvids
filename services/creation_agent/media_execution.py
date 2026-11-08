"""Media tool boundary reuses provider services and durable operation receipts."""

from schemas.agent_workflow import CompletePrompt
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.operation_receipts import execute_step


async def prepare_image_prompt(asset, variant, params):
    execution = current_execution.get()
    if not execution:
        return
    target = variant or asset
    if execution.params.get('creation_plan_id'):
        from services.creation_agent.media_preparation import prepare_planned_media
        await prepare_planned_media(execution, kind='variant' if variant else 'asset', target=target)
        return
    if (target.base_traits or "").strip():
        return
    from services.creation_agent.prompt_standards import CreationPromptStandards

    _, layout = await CreationPromptStandards(asset.novel_id).asset_kind(target)
    result = await execution.generate(
        "image",
        {
            "target": target.canonical_name if variant is None else target.name,
            "description": target.description,
            "asset_type": asset.asset_type,
            "reference_layout": layout,
            "aspect_ratio": params.get("aspect_ratio"),
            "novel_id": asset.novel_id,
        },
        CompletePrompt,
    )
    await execution.before_request()
    from services.creation_objects import project_write as creation_write

    async with creation_write(asset.novel_id):
        await target.refresh_from_db()
        if not (target.base_traits or "").strip():
            target.base_traits = result.prompt
            await target.save(update_fields=["base_traits", "updated_at"])


async def run_image_handler(handler, params):
    execution = current_execution.get()
    if execution is None:
        return await handler.execute(params)
    from models.agent_operation import AgentOperation
    completed = await AgentOperation.get_or_none(task_id=params['task_id'], key='media:image', state='completed')
    if completed:
        return completed.result
    if params.get('creation_plan_id'):
        from models.asset import Asset
        from models.asset_variant import AssetVariant
        asset = await Asset.get(id=params['asset_id'])
        variant = await AssetVariant.get(id=params['variant_id']) if params.get('variant_id') else None
        await prepare_image_prompt(asset, variant, params)

    async def invoke():
        await execution.before_request()
        if params.get('creation_plan_id'):
            from services.creation_agent.media_preparation import validate_prepared_media
            await validate_prepared_media(execution, variant or asset)
        return await handler.execute(params)

    # The image provider is synchronous: recovery never blindly repeats a request
    # whose output could have been lost after the provider accepted it.
    return await execute_step(params["task_id"], "media:image", invoke, external=True)
