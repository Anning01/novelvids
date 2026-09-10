"""Private conversations and atomic admission into the existing task executor."""

import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from auth.deps import AuthContext, ensure_novel_access, require_roles
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentConversation, AgentMessage, AgentSettings
from models.novel import Novel
from models.scene import Scene
from schemas.creation_agent import AgentConfiguration, AgentRunRequest, PromptStatusRequest
from services.ai_task_executor import ai_task_executor
from services.model_resolution import resolve_scope_configs
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


ACTIVE_STATUSES = (TaskStatusEnum.pending.value, TaskStatusEnum.queued.value, TaskStatusEnum.running.value)


async def agent_configuration() -> AgentConfiguration:
    row = await AgentSettings.get_or_none(id=1)
    return AgentConfiguration.model_validate(row.configuration if row else {})


async def agent_models(ctx: AuthContext):
    return await resolve_scope_configs(AiTaskTypeEnum.creation_agent.value, ctx.team_id,
        capability_filter=lambda config: config.supports_tool_calls)


class AgentSessions:
    async def create(self, novel_id: int, ctx: AuthContext) -> AgentConversation:
        await ensure_novel_access(novel_id, ctx)
        novel = await Novel.get_or_none(id=novel_id)
        if novel is None:
            raise HTTPException(404, "项目不存在")
        return await AgentConversation.create(novel=novel, created_by=ctx.user.id if ctx.user else None, team_id=novel.team_id)

    async def get(self, conversation_id: int, ctx: AuthContext) -> AgentConversation:
        conversation = await AgentConversation.get_or_none(id=conversation_id, created_by=ctx.user.id if ctx.user else None)
        if conversation is None:
            raise HTTPException(404, "会话不存在")
        await ensure_novel_access(conversation.novel_id, ctx)
        return conversation

    async def for_task(self, task_id, ctx: AuthContext) -> tuple[AgentConversation, AgentMessage]:
        message = await AgentMessage.get_or_none(task_id=task_id, role="assistant")
        if message is None:
            raise HTTPException(404, "运行不存在")
        return await self.get(message.conversation_id, ctx), message

    async def validate_scope(self, novel_id: int, request: AgentRunRequest | PromptStatusRequest) -> None:
        if request.chapter_id and not await Chapter.filter(id=request.chapter_id, novel_id=novel_id).exists():
            raise HTTPException(404, "章节不存在")
        for target in request.targets:
            if target.kind == "scene":
                query = Scene.filter(id=target.id, chapter__novel_id=novel_id)
            elif target.kind == "asset":
                query = Asset.filter(id=target.id, novel_id=novel_id)
            else:
                query = AssetVariant.filter(id=target.id, asset__novel_id=novel_id)
            if not await query.exists():
                raise HTTPException(404, "当前项目内不存在该目标")

    async def submit(self, conversation: AgentConversation, request: AgentRunRequest, ctx: AuthContext) -> AiTask:
        conversation = await self.get(conversation.id, ctx)
        await require_roles("admin", "creator")(ctx)
        configuration = await agent_configuration()
        if not configuration.enabled:
            raise HTTPException(403, "创作助手尚未启用")
        if len(request.targets) > configuration.max_targets:
            raise HTTPException(422, "选中目标超过本次运行上限")
        await self.validate_scope(conversation.novel_id, request)
        models = await agent_models(ctx)
        chosen = next((model for model in models if request.model_config_id is None or model.id == request.model_config_id), None)
        if chosen is None:
            raise HTTPException(422, "请配置已启用且支持工具调用的创作助手模型")
        payload = request.model_dump(mode="json")
        if 'write_scope' not in request.model_fields_set:
            # Older clients retain their original selected-prompt contract.
            payload.pop('write_scope', None)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        async with in_transaction() as connection:
            # A row write serializes admission on SQLite as well as PostgreSQL.
            await AgentConversation.filter(id=conversation.id).using_db(connection).update(updated_at=datetime.now(timezone.utc))
            current = await AgentConversation.get(id=conversation.id).using_db(connection)
            previous = await AgentMessage.filter(conversation=current, request_id=request.request_id, role="user").using_db(connection).first()
            if previous:
                if previous.request_hash != digest:
                    raise HTTPException(409, "同一请求标识不能对应不同内容")
                return await AiTask.get(id=previous.task_id).using_db(connection)
            if current.active_task_id and await AiTask.filter(id=current.active_task_id, status__in=ACTIVE_STATUSES).using_db(connection).exists():
                raise HTTPException(409, "当前会话仍在执行，请等待完成或停止后继续")
            task = await ai_task_executor.submit(AiTaskTypeEnum.creation_agent, {
                "novel_id": conversation.novel_id, "conversation_id": conversation.id,
                "team_id": ctx.team_id, "user_id": ctx.user.id if ctx.user else None,
                "model_config_id": chosen.id, "agent_configuration": configuration.model_dump(),
            }, db_connection=connection)
            task.request_params = {**task.request_params, "task_id": str(task.id)}
            await task.save(using_db=connection, update_fields=["request_params"])
            await AgentMessage.create(conversation=current, task=task, request_id=request.request_id,
                request_hash=digest, role="user", content=request.message, run_input=payload, using_db=connection)
            await AgentMessage.create(conversation=current, task=task, request_id=request.request_id,
                request_hash=digest, role="assistant", model_snapshot={
                    "id": chosen.id, "name": chosen.name, "model": chosen.model,
                    "scope": chosen.scope, "pricing": chosen.pricing,
                    "image_model_type": None, "video_model_type": None,
                }, using_db=connection)
            await AgentConversation.filter(id=current.id).using_db(connection).update(active_task_id=task.id)
            return task


agent_sessions = AgentSessions()
