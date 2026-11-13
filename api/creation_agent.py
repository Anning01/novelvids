"""Private assistant REST resources and replayable official AG-UI events."""

from utils.messages import localized_message

from uuid import UUID

from ag_ui.core import Event, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter

from auth.deps import AuthContext, get_auth_context, require_super_admin
from controllers.creation_agent import creation_agent_controller
from models.ai_task import AiTask
from schemas.creation_agent import AgentConfiguration, AgentConversationCreate, AgentConversationOut, AgentMessagePage, AgentRunOut, AgentRunRequest, PromptChangeOut, PromptStatusRequest, PromptTargetStatusOut
from services.ai_task_executor import ai_task_executor
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.sessions import ACTIVE_STATUSES, agent_sessions
from services.task_signals import task_signals
from utils.enums import TaskStatusEnum
from utils.response_format import ResponseSchema


router = APIRouter()
_EVENT_ADAPTER = TypeAdapter(Event)
_STREAM_BATCH = 200
_STREAM_IDLE_FALLBACK_SECONDS = 15.0


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
async def conversations(novel_id: int = Query(gt=0), deleted: bool = False, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.conversations(novel_id, ctx, deleted=deleted))


@router.post('/conversations/default', response_model=ResponseSchema[AgentConversationOut])
async def default_conversation(body: AgentConversationCreate, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await agent_sessions.default(body.novel_id, ctx))


@router.post('/conversations', response_model=ResponseSchema[AgentConversationOut])
async def create_conversation(body: AgentConversationCreate, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.create(body.novel_id, ctx))


@router.delete('/conversations/{conversation_id}', response_model=ResponseSchema)
async def delete_conversation(conversation_id: int, ctx: AuthContext = Depends(get_auth_context)):
    await creation_agent_controller.delete_conversation(conversation_id, ctx)
    return ResponseSchema(data=None)


@router.post('/conversations/{conversation_id}/restore', response_model=ResponseSchema[AgentConversationOut])
async def restore_conversation(conversation_id: int, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await creation_agent_controller.restore_conversation(conversation_id, ctx))


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
            raise HTTPException(404, localized_message('运行不存在'))
        if body.messages or body.tools or body.state or body.context or body.forwarded_props:
            raise HTTPException(422, localized_message('事件订阅不接受客户端历史、工具或状态'))
    encoder = EventEncoder()

    def closing_error(task: AiTask, fallback_code: str) -> RunErrorEvent:
        return RunErrorEvent(message=task.error_message or '运行已停止',
            code='CANCELLED' if task.status == TaskStatusEnum.cancelled.value else fallback_code)

    async def events():
        cursor = max(after, int((assistant.run_input or {}).get('stream_start_seq', 0)))
        while not await request.is_disconnected():
            async with task_signals.subscription(str(task_id)) as signal:
                task = await AiTask.get(id=task_id)
                active = task.status in ACTIVE_STATUSES
                while True:
                    batch = await agent_event_log.page(assistant, cursor, _STREAM_BATCH)
                    if not batch:
                        break
                    halted = False
                    for event in batch:
                        if event['type'] in {'RUN_ERROR', 'RUN_FINISHED'}:
                            if active:
                                halted = True
                                break
                            if task.status != TaskStatusEnum.completed.value:
                                yield encoder.encode(closing_error(task, 'FAILED'))
                                return
                        yield encoder.encode(_EVENT_ADAPTER.validate_python(event))
                        cursor += 1
                    if halted or len(batch) < _STREAM_BATCH:
                        break
                if not active:
                    last = await agent_event_log.last(assistant)
                    if last is None or last['type'] not in {'RUN_FINISHED', 'RUN_ERROR'}:
                        yield encoder.encode(closing_error(task, 'INTERRUPTED'))
                    return
                if not await task_signals.wait(signal, _STREAM_IDLE_FALLBACK_SECONDS):
                    # Transport heartbeat only: it neither fabricates progress
                    # nor advances the persisted event cursor.
                    yield ': keep-alive\n\n'

    return StreamingResponse(events(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
