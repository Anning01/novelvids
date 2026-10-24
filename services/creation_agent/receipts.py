"""Public task receipts contain state and identifiers, never model credentials."""

from models.ai_task import AiTask
from models.agent_operation import AgentOperation


async def production_receipts(task_id):
    task = await AiTask.get(id=task_id)
    result = []
    if task.request_params.get("workflow_version") and task.task_type != 7:
        result.append(
            {
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
        )
    for row in await AgentOperation.filter(
        task_id=task_id, state="completed", key__startswith="submit:"
    ):
        child = await AiTask.get_or_none(id=row.result.get("task_id"))
        if child:
            result.append(
                {
                    "task_id": str(child.id),
                    "operation": child.request_params.get("operation")
                    or {
                        1: "assets",
                        2: "image",
                        3: "storyboard",
                        5: "story",
                        6: "remake",
                    }.get(child.task_type, "video"),
                    "status": child.status,
                    "stage": child.stage,
                    "error": child.error_message,
                }
            )
    return result


async def usage_summary(message):
    from models.creation_agent import AgentMessage

    usage = dict(message.usage or {})
    children = await AgentMessage.filter(
        conversation_id=message.conversation_id, role="assistant"
    ).select_related("task")
    for child in children:
        if child.task.request_params.get("parent_task_id") != str(message.task_id):
            continue
        for key in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "summary_requests",
        ):
            usage[key] = usage.get(key, 0) + (child.usage or {}).get(key, 0)
        usage["missing_usage"] = usage.get("missing_usage", False) or (
            child.usage or {}
        ).get("missing_usage", False)
    return usage
