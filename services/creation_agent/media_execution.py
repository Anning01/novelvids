"""Media tool boundary reuses provider services and durable operation receipts."""

from schemas.agent_workflow import CompletePrompt
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.operation_receipts import execute_step


async def prepare_image_prompt(asset, variant, params):
    execution = current_execution.get()
    if not execution:
        return
    target = variant or asset
    if (target.base_traits or "").strip():
        return
    result = await execution.generate(
        "image",
        {
            "target": target.canonical_name if variant is None else target.name,
            "description": target.description,
            "asset_type": asset.asset_type,
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

    async def invoke():
        await execution.before_request()
        return await handler.execute(params)

    # The image provider is synchronous: recovery never blindly repeats a request
    # whose output could have been lost after the provider accepted it.
    return await execute_step(params["task_id"], "media:image", invoke, external=True)
