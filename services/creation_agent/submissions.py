"""Database-unique admission for client retries, independent of process memory."""

from contextvars import ContextVar
import hashlib
import json
from fastapi import HTTPException
from tortoise.transactions import in_transaction
from tortoise.expressions import F
from models.agent_submission import AgentSubmission
from models.ai_task import AiTask
from utils.messages import localized_message

submission: ContextVar[dict | None] = ContextVar("production_submission", default=None)


def envelope(params):
    return {**params, **(submission.get() or {})}


def submission_key(params):
    if not params.get("submission_id"):
        return None
    return hashlib.sha256(
        json.dumps(
            [params.get("team_id"), params.get("user_id"), params["submission_id"]]
        ).encode()
    ).hexdigest()


def validate_receipt(row, task_type, params):
    if row.request_hash != params["submission_hash"] or row.task_type != task_type:
        raise HTTPException(409, localized_message("同一请求标识不能对应不同内容"))


async def previous_submission(task_type, params, connection=None):
    params = envelope(params)
    key = submission_key(params)
    if key is None:
        return None
    row = await AgentSubmission.get_or_none(key=key).using_db(connection)
    if row is None:
        return None
    validate_receipt(row, task_type, params)
    task = (
        await AiTask.get_or_none(id=row.task_id).using_db(connection)
        if row.task_id
        else None
    )
    return task


async def submit_once(task_type, params, create):
    params = envelope(params)
    key = submission_key(params)
    async with in_transaction() as connection:
        if key is None:
            return await create(connection)
        # The unique key arbitrates races across workers; the receipt is never
        # committed without its task. Rollback releases both on admission failure.
        # Acquire SQLite's write lock before the first read; PostgreSQL uses
        # the unique insert and row lock when the key does not exist yet.
        await (
            AgentSubmission.filter(key=key)
            .using_db(connection)
            .update(request_hash=F("request_hash"))
        )
        row, created = await AgentSubmission.get_or_create(
            key=key,
            defaults={
                "request_hash": params["submission_hash"],
                "task_type": task_type,
            },
            using_db=connection,
        )
        await (
            AgentSubmission.filter(id=row.id)
            .using_db(connection)
            .update(request_hash=F("request_hash"))
        )
        row = (
            await AgentSubmission.filter(id=row.id)
            .using_db(connection)
            .select_for_update()
            .get()
        )
        validate_receipt(row, task_type, params)
        if not created:
            task = (
                await AiTask.get_or_none(id=row.task_id).using_db(connection)
                if row.task_id
                else None
            )
            if task is not None:
                return task
        task = await create(connection)
        row.task_id = task.id
        await row.save(using_db=connection, update_fields=["task_id"])
        return task


async def bind_submission(task, params=None):
    from services.creation_agent.skill_execution import user_instruction

    params = envelope(task.request_params if params is None else params)
    from services.creation_agent.skill_execution import current_execution
    execution = current_execution.get()
    expected_plan = params.get('creation_plan_id') or (execution.params.get('creation_plan_id') if execution else None)
    expected_step = params.get('creation_step_id') or (execution.params.get('creation_step_id') if execution else None)
    if (task.request_params.get('creation_plan_id'), task.request_params.get('creation_step_id')) != (expected_plan, expected_step):
        raise HTTPException(409, localized_message('已有任务属于不同创作方案，请等待完成后重试'))
    if task.request_params.get("instruction_message_id") != params.get("instruction_message_id"):
        if await user_instruction(task.request_params) != await user_instruction(params):
            raise HTTPException(409, localized_message("已有任务的创作要求不同，请等待完成或停止后重新提交"))

    async def existing(_connection):
        return task

    return await submit_once(task.task_type, params, existing)
