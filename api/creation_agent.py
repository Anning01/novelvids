"""Private assistant REST resources and replayable official AG-UI events."""

import asyncio
from uuid import UUID

from ag_ui.core import Event, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter

from auth.deps import AuthContext, get_auth_context, require_super_admin
from controllers.creation_agent import creation_agent_controller
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from schemas.creation_agent import AgentConfiguration, AgentConversationCreate, AgentConversationOut, AgentMessagePage, AgentRunOut, AgentRunRequest, PromptChangeOut, PromptStatusRequest, PromptTargetStatusOut
from services.ai_task_executor import ai_task_executor
from services.creation_agent.sessions import ACTIVE_STATUSES, agent_sessions
from utils.enums import TaskStatusEnum
from utils.response_format import ResponseSchema


router = APIRouter()
_EVENT_ADAPTER = TypeAdapter(Event)
_STREAM_POLL_SECONDS = 0.15


@router.get('/capabilities', response_model=ResponseSchema)
async def capabilities(novel_id: int = Query(gt=0), ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.capabilities(novel_id, ctx))


@router.post('/prompt-status', response_model=ResponseSchema[list[PromptTargetStatusOut]])
async def prompt_status(body: PromptStatusRequest, novel_id: int = Query(gt=0), ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.prompt_status(novel_id, body, ctx))


@router.get('/configuration', response_model=ResponseSchema[AgentConfiguration])
async def configuration(_: AuthContext = Depends(require_super_admin)):
    return ResponseSchema(data=await creation_agent_controller.configuration())


@router.put('/configuration', response_model=ResponseSchema[AgentConfiguration])
async def update_configuration(body: AgentConfiguration, _: AuthContext = Depends(require_super_admin)):
    return ResponseSchema(data=await creation_agent_controller.update_configuration(body))


@router.get('/conversations', response_model=ResponseSchema[list[AgentConversationOut]])
async def conversations(novel_id: int = Query(gt=0), ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.conversations(novel_id, ctx))


@router.post('/conversations', response_model=ResponseSchema[AgentConversationOut])
async def create_conversation(body: AgentConversationCreate, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.create(body.novel_id, ctx))


@router.get('/conversations/{conversation_id}/messages', response_model=ResponseSchema[AgentMessagePage])
async def messages(conversation_id: int, before: int | None = Query(None, gt=0), ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.messages(conversation_id, ctx, before))


@router.post('/conversations/{conversation_id}/runs', response_model=ResponseSchema[AgentRunOut])
async def submit(conversation_id: int, body: AgentRunRequest, background_tasks: BackgroundTasks,
                 ctx: AuthContext = Depends(get_auth_context)):
    task = await creation_agent_controller.submit(conversation_id, body, ctx)
    if task.status in ACTIVE_STATUSES:
        background_tasks.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=await creation_agent_controller.snapshot(task.id, ctx))


@router.get('/runs/{task_id}', response_model=ResponseSchema[AgentRunOut])
async def snapshot(task_id: UUID, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.snapshot(task_id, ctx))


@router.post('/runs/{task_id}/stop', response_model=ResponseSchema[AgentRunOut])
async def stop(task_id: UUID, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.stop(task_id, ctx))


@router.post('/changes/{change_id}/undo', response_model=ResponseSchema[PromptChangeOut])
async def undo(change_id: int, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.undo(change_id, ctx))


@router.api_route('/runs/{task_id}/events', methods=['GET', 'POST'])
async def stream(task_id: UUID, request: Request, body: RunAgentInput | None = Body(None),
                 after: int = Query(0, ge=0), ctx: AuthContext = Depends(get_auth_context)):
    conversation, assistant = await agent_sessions.for_task(task_id, ctx)
    if body is not None:
        if body.run_id != str(task_id) or body.thread_id != str(conversation.id):
            raise HTTPException(404, '运行不存在')
        if body.messages or body.tools or body.state or body.context or body.forwarded_props:
            raise HTTPException(422, '事件订阅不接受客户端历史、工具或状态')
    encoder = EventEncoder()

    async def events():
        cursor = after
        while not await request.is_disconnected():
            row = await AgentMessage.get(id=assistant.id)
            task = await AiTask.get(id=task_id)
            active = task.status in ACTIVE_STATUSES
            while cursor < len(row.events):
                event = row.events[cursor]
                if event['type'] in {'RUN_ERROR', 'RUN_FINISHED'}:
                    if active:
                        break
                    if task.status != TaskStatusEnum.completed.value:
                        yield encoder.encode(RunErrorEvent(message=task.error_message or '运行已停止',
                            code='CANCELLED' if task.status == TaskStatusEnum.cancelled.value else 'FAILED'))
                        return
                yield encoder.encode(_EVENT_ADAPTER.validate_python(event))
                cursor += 1
            if not active:
                if not row.events or row.events[-1]['type'] not in {'RUN_FINISHED', 'RUN_ERROR'}:
                    yield encoder.encode(RunErrorEvent(message=task.error_message or '运行已停止',
                        code='CANCELLED' if task.status == TaskStatusEnum.cancelled.value else 'INTERRUPTED'))
                return
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(events(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
