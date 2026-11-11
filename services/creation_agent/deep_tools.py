"""Expose the existing validated business tools to Deep Agents without duplicating writers."""

import asyncio
import inspect

from langchain_core.tools import StructuredTool, ToolException
from langchain_core.callbacks.manager import adispatch_custom_event
from services.creation_agent.skill_stream import skill_event_sink
from langchain.tools import ToolRuntime
from pydantic import ValidationError
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.usage import RunUsage
from schemas.creation_agent import CreationConstraintProposal
from services.creation_agent.memory import creation_memory

from services.creation_agent import runtime


async def remember_creation_constraints(ctx: RunContext, constraints: list[CreationConstraintProposal]) -> dict:
    """保存用户本轮明确提出的长期创作要求；来源必须逐字引用本轮用户原话。"""
    await ctx.deps.changes.authorize()
    saved = await creation_memory.save(ctx.deps.source_message, constraints)
    ctx.model.message.usage['remembered_rules'] = [{'content': rule.content, 'scope': rule.scope} for rule in saved]
    await ctx.model.message.save(update_fields=['usage'])
    return {'status': 'saved', 'rules': [{'id': rule.id, 'content': rule.content, 'scope': rule.scope} for rule in saved]}


async def business_tools(deps, model, before_request):
    names = (
        'get_creation_context', 'query_creation_objects', 'get_creation_prompt_rules',
        'read_creation_objects', 'read_creation_history', 'patch_creation_prompts',
        'create_creation_setting', 'undo_creation_change',
        'revise_creation_object', 'get_production_context', 'submit_production', 'remember_creation_constraints',
    ) if deps.changes else ('get_creation_context', 'update_image_prompt', 'update_storyboard_prompt')
    if deps.changes and deps.changes.request.write_scope == 'read_only':
        names = tuple(name for name in names if name in {'get_creation_context', 'query_creation_objects',
            'get_creation_prompt_rules', 'read_creation_objects', 'read_creation_history', 'get_production_context'})
    native = {name: Tool(remember_creation_constraints if name == 'remember_creation_constraints' else getattr(runtime, name)) for name in names}
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
