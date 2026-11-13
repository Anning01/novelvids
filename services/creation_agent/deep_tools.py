"""Expose the existing validated business tools to Deep Agents without duplicating writers."""

import asyncio
import inspect
from typing import Annotated

from langchain_core.tools import StructuredTool, ToolException
from langchain_core.callbacks.manager import adispatch_custom_event
from services.creation_agent.skill_stream import skill_event_sink
from langchain.tools import ToolRuntime
from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.usage import RunUsage
from schemas.creation_agent import CreationConstraintProposal
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.memory import creation_memory

from services.creation_agent import runtime


async def remember_creation_constraints(ctx: RunContext, constraints: list[CreationConstraintProposal]) -> dict:
    """保存用户本轮明确提出的长期创作要求；来源必须逐字引用本轮用户原话。"""
    await ctx.deps.changes.authorize()
    saved = await creation_memory.save(ctx.deps.source_message, constraints)
    ctx.model.message.usage['remembered_rules'] = [{'content': rule.content, 'scope': rule.scope} for rule in saved]
    await ctx.model.message.save(update_fields=['usage'])
    return {'status': 'saved', 'rules': [{'id': rule.id, 'content': rule.content, 'scope': rule.scope} for rule in saved]}


async def link_scene_references(ctx: RunContext, scene_id: Annotated[int, Field(gt=0)],
                                asset_ids: Annotated[list[int], Field(max_length=30)],
                                variant_ids: Annotated[list[int], Field(max_length=30)],
                                prompt: Annotated[str | None, Field(min_length=1, max_length=32000)] = None) -> dict:
    """引用已登记设定及其形态，不新建卡片；先读取目标分镜。历史手工提示词需同时提交保留原意的完整 prompt。"""
    fields = {'assets': asset_ids, 'variant_refs': variant_ids}
    if prompt is not None:
        fields['prompt'] = prompt
    changes = CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_scene', 'scene_id': scene_id, 'fields': fields,
    }]})
    return runtime.change_receipt(await ctx.deps.changes.apply(changes, tool_call_id=ctx.tool_call_id or ''))


async def read_episode_script(ctx: RunContext, chapter_id: Annotated[int, Field(gt=0)], page: Annotated[int, Field(ge=1)] = 1) -> dict:
    """读取本作品导演剧本正文与当前版本；长正文按页读取。"""
    return await ctx.deps.changes.read_episode_script(chapter_id, page)


async def revise_episode_script(ctx: RunContext, chapter_id: Annotated[int, Field(gt=0)],
    content: Annotated[str, Field(min_length=1, max_length=128000)], name: Annotated[str | None, Field(min_length=1, max_length=255)] = None) -> dict:
    """保存本轮授权集的完整导演稿；先读完正文，校验并发修改，记录差异并支持撤销，不改集号。"""
    return runtime.change_receipt(await ctx.deps.changes.revise_episode_script(chapter_id, content, name, ctx.tool_call_id))


async def business_tools(deps, model, before_request):
    names = (
        'get_creation_context', 'query_creation_objects', 'get_creation_prompt_rules',
        'read_creation_objects', 'read_creation_history', 'patch_creation_prompts',
        'create_creation_setting', 'undo_creation_change', 'link_scene_references', 'read_episode_script', 'revise_episode_script',
        'revise_creation_object', 'get_production_context', 'submit_production', 'remember_creation_constraints',
    ) if deps.changes else ('get_creation_context', 'update_image_prompt', 'update_storyboard_prompt')
    if deps.changes and deps.changes.request.write_scope == 'read_only':
        names = tuple(name for name in names if name in {'get_creation_context', 'query_creation_objects',
            'get_creation_prompt_rules', 'read_creation_objects', 'read_creation_history', 'get_production_context', 'read_episode_script'})
    local = {'remember_creation_constraints': remember_creation_constraints, 'link_scene_references': link_scene_references, 'read_episode_script': read_episode_script, 'revise_episode_script': revise_episode_script}
    native = {name: Tool(local[name] if name in local else getattr(runtime, name)) for name in names}
    context = RunContext(deps=deps, model=model, usage=RunUsage())
    definitions = await runtime.prepare_creation_tools(context, [tool.tool_def for tool in native.values()])
    lock = asyncio.Lock()

    def expose(definition):
        original = native[definition.name]

        async def invoke(runtime: ToolRuntime, **arguments):
            async with lock:
                await before_request()
                context = RunContext(deps=deps, model=model, usage=RunUsage(),
                    tool_call_id=runtime.tool_call_id, tool_name=definition.name)
                active = True

                async def forward(event):
                    if active:
                        await adispatch_custom_event('creation_agent_activity', event, config=runtime.config)

                token = skill_event_sink.set(forward)
                try:
                    parsed = original.function_schema.validator.validate_python(arguments)
                    result = original.function(context, **parsed)
                    return await result if inspect.isawaitable(result) else result
                except ValidationError as error:
                    raise ToolException(str(error.errors(include_input=False))) from None
                except (ModelRetry, ValueError) as error:
                    raise ToolException(str(error)) from None
                finally:
                    active = False
                    skill_event_sink.reset(token)

        return StructuredTool(name=definition.name, description=definition.description or definition.name,
            coroutine=invoke, args_schema=definition.parameters_json_schema, handle_tool_error=True)

    return [expose(definition) for definition in definitions]
