"""Pydantic AI runtime; the framework owns the tool loop and AG-UI encoding."""

from dataclasses import dataclass, field
from collections.abc import AsyncIterator, Sequence, Callable, Awaitable
from typing import Annotated
import re

from ag_ui.core import BaseEvent, RunAgentInput, UserMessage
from pydantic import Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.ui.ag_ui import AGUIAdapter
from pydantic_ai.usage import UsageLimits
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.settings import ModelSettings

from prompts.creation_agent import CREATION_AGENT_INSTRUCTIONS, render_creation_request
from schemas.creation_agent import ImagePromptEdit, StoryboardPromptEdit, CreationReply
from models.creation_agent import AgentMessage, PromptChange
from services.creation_agent.tools import PromptEditService


@dataclass
class CreationAgentDeps:
    service: PromptEditService
    context: dict
    source_message: AgentMessage | None = None
    context_loader: Callable[[int | None], Awaitable[dict]] | None = None
    observed_versions: dict[tuple[str, int], str] = field(default_factory=dict)


creation_agent = Agent(
    deps_type=CreationAgentDeps,
    instructions=CREATION_AGENT_INSTRUCTIONS,
    name="creation_assistant",
    output_type=[str, CreationReply],
    retries=2,
)

_TECHNICAL_REPLY_REFERENCE = re.compile(
    r"(?i)(?:\b(?:scene(?:_id)?|asset(?:_id)?|target_id)\s*[:#：]?\s*\d+\b|场景\s*\d+)"
)


@creation_agent.output_validator
async def validate_creative_memory(ctx: RunContext[CreationAgentDeps], output: str | CreationReply):
    message = output.message if isinstance(output, CreationReply) else output
    if _TECHNICAL_REPLY_REFERENCE.search(message):
        raise ModelRetry("最终回复请只使用用户可见的对象名称，不展示内部ID或scene_id")
    if isinstance(output, CreationReply) and output.constraints:
        from services.creation_agent.memory import creation_memory
        if ctx.deps.source_message is None:
            raise ModelRetry("当前运行没有可验证的用户消息来源，不能保存长期约束")
        try:
            await creation_memory.validate(ctx.deps.source_message, output.constraints)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from None
    return output


@creation_agent.tool
async def get_creation_context(ctx: RunContext[CreationAgentDeps], chapter_offset: Annotated[int | None, Field(ge=0)] = None) -> dict:
    """读取当前授权目标和约束；chapter_offset 可按字符位置读取当前章的有界正文片段。"""
    if ctx.deps.context_loader:
        try:
            ctx.deps.context = await ctx.deps.context_loader(chapter_offset)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from None
    targets = await ctx.deps.service.read_targets(for_model=True)
    ctx.deps.observed_versions = {
        (target["kind"], target["id"]): target["version"] for target in targets
    }
    model_targets = []
    for target in targets:
        item = dict(target)
        item.pop("version", None)
        model_targets.append(item)
    return {"context": ctx.deps.context, "targets": model_targets}


def _inject_observed_versions(ctx: RunContext[CreationAgentDeps], edits):
    versioned = []
    for edit in edits:
        key = (("scene", edit.scene_id) if isinstance(edit, StoryboardPromptEdit)
               else (edit.target_kind, edit.target_id))
        version = ctx.deps.observed_versions.get(key)
        if version is None:
            raise ModelRetry("写入前请先调用 get_creation_context 读取当前目标")
        versioned.append(edit.model_copy(update={"expected_version": version}))
    return versioned


def _remember_saved_versions(deps: CreationAgentDeps, result: PromptChange) -> None:
    for item in result.changes:
        deps.observed_versions[(item["kind"], item["target_id"])] = item["after_version"]


@creation_agent.tool
async def update_image_prompt(ctx: RunContext[CreationAgentDeps], edits: list[ImagePromptEdit]) -> dict:
    """修改已授权资产或已有形态的图片 Prompt，保持其他字段和素材绑定。"""
    try:
        result = await ctx.deps.service.update_image_prompt(
            _inject_observed_versions(ctx, edits), tool_call_id=ctx.tool_call_id or ""
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None
    _remember_saved_versions(ctx.deps, result)
    return change_receipt(result)


@creation_agent.tool
async def update_storyboard_prompt(ctx: RunContext[CreationAgentDeps], edits: list[StoryboardPromptEdit]) -> dict:
    """修改已授权分镜的 Prompt；程序完成局部编号、引用展开和一致性保存。"""
    try:
        result = await ctx.deps.service.update_storyboard_prompt(
            _inject_observed_versions(ctx, edits), tool_call_id=ctx.tool_call_id or ""
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None
    _remember_saved_versions(ctx.deps, result)
    return change_receipt(result)


def change_receipt(change: PromptChange) -> dict:
    # Full snapshots remain in PromptChange for the UI/undo API. Echoing them
    # into the model duplicates long prompts and can prevent the final reply.
    return {'status': 'reverted' if change.reverted_at else 'saved', 'change_id': change.id,
            'changes': [{key: value for key, value in item.items()
                         if key in {'kind', 'target_id', 'asset_id'}} for item in change.changes]}


async def stream_creation_agent(
    *, message: str, conversation_id: str, run_id: str,
    model: Model, deps: CreationAgentDeps, usage_limits: UsageLimits,
    message_history: Sequence[ModelMessage] = (),
    model_settings: ModelSettings | None = None,
    on_complete: Callable[[AgentRunResult], Awaitable[None] | AsyncIterator[BaseEvent]] | None = None,
) -> AsyncIterator[BaseEvent]:
    # Build the protocol envelope on the server: never accept client tools or system messages.
    run_input = RunAgentInput(
        thread_id=conversation_id, run_id=run_id,
        messages=[UserMessage(id=f"{run_id}:user", content=render_creation_request(message))],
        tools=[], context=[], state={}, forwarded_props={},
    )
    adapter = AGUIAdapter(agent=creation_agent, run_input=run_input)
    async for event in adapter.run_stream(
        model=model, deps=deps, usage_limits=usage_limits, message_history=message_history,
        model_settings=model_settings, on_complete=on_complete,
    ):
        yield event
