"""Public task receipts contain state and identifiers, never model credentials."""

from models.ai_task import AiTask
from models.agent_operation import AgentOperation


def receipt_of(task) -> dict:
    """Project one task the way production receipts have always reported it."""
    return {
        "task_id": str(task.id),
        "operation": task.request_params.get("operation")
        or {
            1: "assets",
            2: "image",
            3: "storyboard",
            5: "story",
            6: "remake",
        }.get(task.task_type, "video"),
        "status": task.status,
        "stage": task.stage,
        "error": task.error_message,
    }


async def production_receipts_for(tasks) -> dict[str, list[dict]]:
    """Batch receipts for a history page: one operation query and one child lookup."""
    receipts = {
        str(task.id): ([receipt_of(task)]
                       if task.request_params.get("workflow_version") and task.task_type != 7 else [])
        for task in tasks
    }
    if not tasks:
        return receipts
    operations = await AgentOperation.filter(
        task_id__in=[task.id for task in tasks], state="completed", key__startswith="submit:"
    )
    child_ids = [row.result.get("task_id") for row in operations if row.result.get("task_id")]
    children = {str(child.id): child for child in await AiTask.filter(id__in=child_ids)} if child_ids else {}
    for row in operations:
        child = children.get(str(row.result.get("task_id")))
        if child:
            receipts[str(row.task_id)].append(receipt_of(child))
    return receipts


async def production_receipts(task_id):
    task = await AiTask.get(id=task_id)
    return (await production_receipts_for([task]))[str(task.id)]


async def usage_summaries(messages) -> dict[int, dict]:
    """Aggregate child-run usage per message; one conversation load for a whole page."""
    from models.creation_agent import AgentMessage

    summaries = {message.id: dict(message.usage or {}) for message in messages}
    if not messages:
        return summaries
    children: dict[str, list] = {}
    rows = await AgentMessage.filter(
        conversation_id__in={message.conversation_id for message in messages}, role="assistant"
    ).select_related("task")
    for child in rows:
        parent = (child.task.request_params or {}).get("parent_task_id")
        if parent:
            children.setdefault(parent, []).append(child)
    for message in messages:
        summary = summaries[message.id]
        for child in children.get(str(message.task_id), ()):
            for key in (
                "requests",
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "summary_requests",
            ):
                summary[key] = summary.get(key, 0) + (child.usage or {}).get(key, 0)
            summary["missing_usage"] = summary.get("missing_usage", False) or (
                child.usage or {}
            ).get("missing_usage", False)
    return summaries


async def usage_summary(message):
    return (await usage_summaries([message]))[message.id]
