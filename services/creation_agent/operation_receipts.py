"""At-most-once external submission, with recoverable deterministic results."""

from utils.messages import localized_message

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from utils.enums import TaskStatusEnum


class SubmissionUncertain(RuntimeError):
    pass


async def execute_step(task_id, key: str, action, *, external=False, atomic=False):
    row, _ = await AgentOperation.get_or_create(
        task_id=task_id, key=key, defaults={"external": external}
    )
    if row.state == "completed":
        return row.result
    if not await AiTask.filter(
        id=task_id, status=TaskStatusEnum.running.value
    ).exists():
        raise ValueError(localized_message("运行已停止，不能提交后续步骤"))
    claimed = await AgentOperation.filter(id=row.id, state="pending").update(
        state="running"
    )
    if not claimed:
        raise SubmissionUncertain(
            localized_message("步骤执行中或结果待核对，不能重复提交")
        )
    try:
        if atomic:
            from tortoise.transactions import in_transaction

            async with in_transaction():
                result = await action()
                await AgentOperation.filter(id=row.id).update(
                    state="completed", result=result
                )
        else:
            result = await action()
            await AgentOperation.filter(id=row.id).update(
                state="completed", result=result
            )
    except BaseException:
        await AgentOperation.filter(id=row.id).update(
            state="uncertain" if external else "failed"
        )
        raise
    return result


async def record_once(task_id, key, action):
    from tortoise.transactions import in_transaction
    from tortoise.expressions import F

    async with in_transaction() as connection:
        await (
            AiTask.filter(id=task_id)
            .using_db(connection)
            .update(updated_at=F("updated_at"))
        )
        await AiTask.filter(id=task_id).using_db(connection).select_for_update().get()
        row, _ = await AgentOperation.get_or_create(
            task_id=task_id, key=key, using_db=connection
        )
        if row.state == "completed":
            return
        await action()
        row.state = "completed"
        await row.save(using_db=connection, update_fields=["state"])
