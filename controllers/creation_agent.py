"""Creation-assistant application flows and private response projections."""

from datetime import datetime, timezone

from fastapi import HTTPException

from auth.deps import AuthContext, ensure_novel_access, require_roles
from models.ai_task import AiTask
from models.creation_agent import AgentConversation, AgentMessage, PromptChange, AgentSettings
from schemas.creation_agent import AgentConfiguration, AgentRunOut, AgentRunRequest, PromptStatusRequest
from services.creation_agent.memory import creation_memory
from services.creation_agent.handler import authorize_run
from services.creation_agent.sessions import ACTIVE_STATUSES, agent_sessions, agent_configuration, agent_models
from services.creation_agent.tools import PromptEditService, PromptEditConflict
from utils.enums import TaskStatusEnum


def change_projection(change: PromptChange) -> dict:
    return {"id": change.id, "task_id": str(change.task_id), "changes": change.changes,
            "reverted_at": change.reverted_at, "created_at": change.created_at}


class CreationAgentController:
    async def prompt_status(self, novel_id: int, request: PromptStatusRequest, ctx: AuthContext):
        await ensure_novel_access(novel_id, ctx)
        await agent_sessions.validate_scope(novel_id, request)
        return await creation_memory.prompt_status(novel_id, request)

    async def configuration(self):
        return await agent_configuration()

    async def update_configuration(self, body: AgentConfiguration):
        await AgentSettings.update_or_create(id=1, defaults={"configuration": body.model_dump()})
        return body

    async def capabilities(self, novel_id: int, ctx: AuthContext):
        await ensure_novel_access(novel_id, ctx)
        limits = await agent_configuration()
        try:
            await require_roles('admin', 'creator')(ctx)
            can_write = True
        except HTTPException:
            can_write = False
        return {"enabled": limits.enabled, "can_write": can_write, "max_targets": limits.max_targets,
                "models": [{"id": item.id, "name": item.name, "model": item.model} for item in await agent_models(ctx)]}

    async def conversations(self, novel_id: int, ctx: AuthContext):
        await ensure_novel_access(novel_id, ctx)
        return await AgentConversation.filter(novel_id=novel_id, created_by=ctx.user.id if ctx.user else None).order_by('-updated_at').limit(30)

    async def create(self, novel_id: int, ctx: AuthContext):
        return await agent_sessions.create(novel_id, ctx)

    async def submit(self, conversation_id: int, request: AgentRunRequest, ctx: AuthContext):
        conversation = await agent_sessions.get(conversation_id, ctx)
        return await agent_sessions.submit(conversation, request, ctx)

    async def snapshot(self, task_id, ctx: AuthContext) -> AgentRunOut:
        conversation, assistant = await agent_sessions.for_task(task_id, ctx)
        task = await AiTask.get(id=task_id)
        changes = await PromptChange.filter(task_id=task_id, novel_id=conversation.novel_id).order_by('id')
        return AgentRunOut(task_id=task.id, conversation_id=conversation.id, status=task.status,
            content=assistant.content, error_message=task.error_message,
            changes=[change_projection(change) for change in changes], usage=assistant.usage,
            event_count=len(assistant.events))

    async def messages(self, conversation_id: int, ctx: AuthContext, before: int | None):
        conversation = await agent_sessions.get(conversation_id, ctx)
        query = AgentMessage.filter(conversation=conversation)
        if before is not None:
            query = query.filter(id__lt=before)
        rows = await query.order_by('-id').select_related('task').limit(50)
        changes = await PromptChange.filter(task_id__in=[row.task_id for row in rows]).order_by('id')
        return {"items": [{"id": row.id, "role": row.role, "content": row.content,
                           "task_id": str(row.task_id), "status": row.task.status,
                           "created_at": row.created_at,
                           "changes": [change_projection(change) for change in changes if change.task_id == row.task_id] if row.role == 'assistant' else [],
                           "usage": row.usage if row.role == 'assistant' else {}}
                          for row in reversed(rows)],
                "next_before": rows[-1].id if len(rows) == 50 else None}

    async def stop(self, task_id, ctx: AuthContext):
        await agent_sessions.for_task(task_id, ctx)
        await require_roles('admin', 'creator')(ctx)
        await AiTask.filter(id=task_id, status__in=ACTIVE_STATUSES).update(
            status=TaskStatusEnum.cancelled.value, finished_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        return await self.snapshot(task_id, ctx)

    async def undo(self, change_id: int, ctx: AuthContext):
        change = await PromptChange.get_or_none(id=change_id)
        if change is None:
            raise HTTPException(404, '修改记录不存在')
        await agent_sessions.for_task(change.task_id, ctx)
        await require_roles('admin', 'creator')(ctx)
        task = await AiTask.get(id=change.task_id)
        user_message = await AgentMessage.get(task=task, role='user')
        request = AgentRunRequest.model_validate(user_message.run_input)
        limits = AgentConfiguration.model_validate(task.request_params['agent_configuration'])
        async def check():
            await authorize_run(task.request_params)
        service = PromptEditService(novel_id=change.novel_id, task_id=task.id,
            allowed_targets={(target.kind, target.id) for target in request.targets}, max_batch_size=limits.max_targets,
            authorization_check=check)
        try:
            result = await service.undo(change_id)
        except PromptEditConflict as exc:
            raise HTTPException(409, str(exc)) from None
        return change_projection(result)


creation_agent_controller = CreationAgentController()
