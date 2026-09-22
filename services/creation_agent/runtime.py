"""Pydantic AI runtime; the framework owns the tool loop and AG-UI encoding."""

from dataclasses import dataclass, field, replace
from collections.abc import AsyncIterator, Sequence, Callable, Awaitable
from typing import Annotated, Literal
from copy import deepcopy
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

from prompts.creation_agent import CREATION_AGENT_INSTRUCTIONS, CREATION_CRUD_INSTRUCTIONS, render_creation_request
from schemas.creation_agent import AgentConfiguration, ImagePromptEdit, StoryboardPromptEdit, CreationReply, AgentTarget
from schemas.creation_objects import CreationObjectQuery, CreationChangeSet, CreationPromptPatch
from models.creation_agent import AgentMessage, PromptChange
from services.creation_agent.tools import PromptEditService
from services.creation_agent.changes import CreationChanges
from services.creation_agent.history import compact_retry_history


@dataclass
class CreationAgentDeps:
    service: PromptEditService
    context: dict
    source_message: AgentMessage | None = None
    context_loader: Callable[[int | None], Awaitable[dict]] | None = None
    observed_versions: dict[tuple[str, int], str] = field(default_factory=dict)
    changes: CreationChanges | None = None
    limits: AgentConfiguration = field(default_factory=AgentConfiguration)
    tools_enabled: bool = False
    enabled_capabilities: set[str] = field(default_factory=set)
    read_cache: dict = field(default_factory=dict)


def _referenced_definitions(schema: dict) -> set[str]:
    references: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            reference = value.get('$ref')
            if isinstance(reference, str) and reference.startswith('#/$defs/'):
                references.add(reference.rsplit('/', 1)[-1])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk({key: value for key, value in schema.items() if key != '$defs'})
    definitions = schema.get('$defs', {})
    pending = list(references)
    while pending:
        name = pending.pop()
        before = set(references)
        walk(definitions.get(name, {}))
        pending.extend(references - before)
    return references


def _narrow_change_schema(schema: dict, capabilities: set[str]) -> dict:
    """Expose only operation variants authorized for this run step."""
    schema = deepcopy(schema)
    items = schema['properties']['operations']['items']
    variants = []
    mapping = {}
    create_setting = bool(capabilities.intersection({'create', 'create_setting'}))
    create_scene = bool(capabilities.intersection({'create', 'create_scene'}))
    update_setting = bool(capabilities.intersection({'update', 'update_setting'}))
    update_scene = bool(capabilities.intersection({'update', 'update_scene'}))
    if create_setting:
        setting = {
            'discriminator': {
                'mapping': {
                    'asset': '#/$defs/CreateAssetSetting',
                    'variant': '#/$defs/CreateVariantSetting',
                },
                'propertyName': 'kind',
            },
            'oneOf': [
                {'$ref': '#/$defs/CreateAssetSetting'},
                {'$ref': '#/$defs/CreateVariantSetting'},
            ],
        }
        variants.append(setting)
        mapping['create_setting'] = setting
    if create_scene:
        variants.append({'$ref': '#/$defs/CreateScene'})
        mapping['create_scene'] = '#/$defs/CreateScene'
    if update_setting:
        variants.append({'$ref': '#/$defs/UpdateSetting'})
        mapping['update_setting'] = '#/$defs/UpdateSetting'
    if update_scene:
        variants.append({'$ref': '#/$defs/UpdateScene'})
        mapping['update_scene'] = '#/$defs/UpdateScene'
    if 'delete' in capabilities:
        variants.append({'$ref': '#/$defs/DeleteObject'})
        mapping['delete'] = '#/$defs/DeleteObject'
    items['oneOf'] = variants
    items['discriminator']['mapping'] = mapping
    required = _referenced_definitions(schema)
    schema['$defs'] = {name: value for name, value in schema.get('$defs', {}).items() if name in required}
    return schema


async def prepare_creation_tools(ctx: RunContext[CreationAgentDeps], definitions):
    legacy = {'update_image_prompt', 'update_storyboard_prompt'}
    current = {'query_creation_objects', 'read_creation_objects', 'apply_creation_changes', 'undo_creation_change'}
    # Historical selected-prompt runners remain replayable. Each live run sees
    # exactly one set of writers, never two competing business contracts.
    omitted = legacy if ctx.deps.changes else current | {'read_creation_history', 'patch_creation_prompts'}
    capabilities = (
        {'query', 'read', 'create', 'update', 'delete', 'undo'}
        if ctx.deps.tools_enabled
        else ctx.deps.enabled_capabilities
    )
    if ctx.deps.changes:
        if not capabilities:
            omitted |= current
        else:
            if 'query' not in capabilities:
                omitted.add('query_creation_objects')
            if 'read' not in capabilities:
                omitted.add('read_creation_objects')
            if not capabilities.intersection({
                'create', 'create_setting', 'create_scene',
                'update', 'update_setting', 'update_scene', 'delete',
            }):
                omitted.add('apply_creation_changes')
            if 'undo' not in capabilities:
                omitted.add('undo_creation_change')
    prepared = [definition for definition in definitions if definition.name not in omitted]
    if ctx.deps.changes and capabilities.intersection({
        'create', 'create_setting', 'create_scene',
        'update', 'update_setting', 'update_scene', 'delete',
    }):
        prepared = [
            replace(
                definition,
                parameters_json_schema=_narrow_change_schema(
                    definition.parameters_json_schema,
                    capabilities,
                ),
            ) if definition.name == 'apply_creation_changes' else definition
            for definition in prepared
        ]
    return prepared


def creation_instructions(ctx: RunContext[CreationAgentDeps]):
    return CREATION_CRUD_INSTRUCTIONS if ctx.deps.changes else CREATION_AGENT_INSTRUCTIONS


async def process_working_history(ctx: RunContext[CreationAgentDeps], messages: list[ModelMessage]):
    budget = getattr(ctx.model, 'budget', None)
    return budget.restore_projection(compact_retry_history(messages)) if budget else compact_retry_history(messages)


creation_agent = Agent(
    deps_type=CreationAgentDeps,
    instructions=creation_instructions,
    prepare_tools=prepare_creation_tools,
    name="creation_assistant",
    output_type=[str, CreationReply],
    retries=2,
    history_processors=[process_working_history],
)

_TECHNICAL_REPLY_REFERENCE = re.compile(
    r"(?i)(?:\b(?:scene_id|asset_id|asset_type|target_id|change_id|chapter_id|variant_refs|variant_bindings|client_ref)\b"
    r"|\b(?:scene|asset|id)\s*[:#：]?\s*\d+\b|场景\s*\d+)"
)


@creation_agent.output_validator
async def validate_creative_memory(ctx: RunContext[CreationAgentDeps], output: str | CreationReply):
    message = output.message if isinstance(output, CreationReply) else output
    if _TECHNICAL_REPLY_REFERENCE.search(message):
        raise ModelRetry("最终回复请使用用户可见的对象名称和人物、场景、道具等中文类别，不展示内部ID或字段名")
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
async def get_creation_context(ctx: RunContext[CreationAgentDeps], chapter_offset: Annotated[int | None, Field(ge=0)] = None,
                               changes_page: Annotated[int, Field(ge=1)] = 1,
                               include_targets: bool = False, include_catalog: bool = False,
                               include_chapter: bool = False, include_project: bool = False,
                               include_changes: bool = False,
                               include_creation_rules: bool = False,
                               capabilities: list[Literal[
                                   'query', 'read', 'create_setting', 'create_scene',
                                   'update_setting', 'update_scene', 'delete', 'undo',
                               ]] | None = None) -> dict:
    """读取当前上下文与约束；chapter_offset 读取正文片段，changes_page 翻页查本会话实际操作记录。"""
    if ctx.deps.context_loader:
        try:
            ctx.deps.context = await ctx.deps.context_loader(chapter_offset if chapter_offset is not None else 0 if include_chapter else None)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from None
    if ctx.deps.changes:
        service = ctx.deps.changes
        await service.authorize()
        ctx.deps.enabled_capabilities.update(capabilities or [])
        targets = project_read_items(
            ctx,
            await service.read(service.request.targets, use_cache=True),
        ) if include_targets and service.request.targets else []
        prospective = (
            await service.read_creation_context(service.request.chapter_id)
            if include_creation_rules and service.request.chapter_id
            else {}
        )
        context = dict(ctx.deps.context)
        if include_project:
            from models.novel import Novel
            project = await Novel.get(id=service.novel_id)
            offset = chapter_offset or 0
            length = ctx.deps.limits.context_page_characters
            context['project_details'] = {key: {'text': (value or '')[offset:offset + length],
                'next_offset': offset + length if offset + length < len(value or '') else None}
                for key, value in [('outline', project.story_outline), ('setting', project.project_setting)]}
        selected = []
        for ref in service.request.targets:
            obj = await service.creative_target(ref.kind, ref.id)
            from services.creation_agent.object_state import object_label
            selected.append({**ref.model_dump(), 'name': await object_label(obj)})
        return {'context': context, 'selected_targets': selected, 'targets': targets,
                'write_scope': service.request.write_scope,
                'catalog': await service.catalog.search(CreationObjectQuery()) if include_catalog and service.request.chapter_id else None,
                'recent_changes': await service.recent_changes(ctx.deps.source_message, changes_page) if include_changes or changes_page > 1 else None,
                **prospective}
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
                         if key in {'kind', 'target_id', 'asset_id', 'operation', 'target_label', 'chapter_id'}} for item in change.changes]}


def crud_service(ctx: RunContext[CreationAgentDeps]) -> CreationChanges:
    if ctx.deps.changes is None:
        raise ModelRetry('当前运行不支持对象管理')
    return ctx.deps.changes


@creation_agent.tool
async def query_creation_objects(ctx: RunContext[CreationAgentDeps], query: CreationObjectQuery,
                                 references_of: AgentTarget | None = None) -> dict:
    """查询当前项目的轻量目录；references_of 可查询对象的引用关系，不产生修改。"""
    service = crud_service(ctx)
    try:
        await service.authorize()
        if references_of:
            return await service.catalog.references(references_of.kind, references_of.id, page=query.page, page_size=query.page_size)
        return await service.catalog.search(query)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


def project_read_items(ctx, items, fields=None, prompt_offset=0):
    service = crud_service(ctx)
    from services.creation_agent.context_budget import encode
    from services.creation_agent.tools import _digest
    generation = getattr(getattr(ctx.model, 'budget', None), 'compactions', 0)
    for item in items:
        if fields is None and item.get('edit_mode') == 'changes':
            item.pop('prompt', None)
        if fields is not None:
            for key in ('prompt', 'prompt_params', 'fields', 'references', 'entities'):
                if key not in fields:
                    item.pop(key, None)
        prompt = item.get('prompt')
        if isinstance(prompt, str):
            length = ctx.deps.limits.context_page_characters
            if prompt_offset > len(prompt):
                raise ValueError('提示词读取位置超出范围')
            item['prompt'] = prompt[prompt_offset:prompt_offset + length]
            item['prompt_truncated'] = prompt_offset > 0 or prompt_offset + length < len(prompt)
            item['prompt_next_offset'] = prompt_offset + length if prompt_offset + length < len(prompt) else None
            item['prompt_characters'] = len(prompt)
            target_key = (item['kind'], item['id'])
            if item['prompt_truncated']:
                service.partial_prompts.add(target_key)
            else:
                service.partial_prompts.discard(target_key)
        key = (item['kind'], item['id'], encode(fields), prompt_offset)
        digest = _digest(item)
        previous = ctx.deps.read_cache.get(key)
        if previous and previous[:2] == (digest, generation):
            item.clear()
            item.update(kind=key[0], id=key[1], unchanged=True, previous_tool_call_id=previous[2])
        else:
            ctx.deps.read_cache[key] = (digest, generation, ctx.tool_call_id)
    return items


@creation_agent.tool
async def read_creation_objects(ctx: RunContext[CreationAgentDeps], targets: list[AgentTarget],
                                chapter_id: Annotated[int | None, Field(gt=0)] = None,
                                chapter_offset: Annotated[int | None, Field(ge=0)] = None,
                                fields: list[Literal['prompt', 'prompt_params', 'fields', 'references', 'entities']] | None = None,
                                prompt_offset: Annotated[int, Field(ge=0)] = 0) -> dict:
    """读取已有对象详情和约束；空 targets 可读取指定章的正文及约束，chapter_offset 按字符分页。"""
    service = crud_service(ctx)
    try:
        prospective = await service.read_creation_context(chapter_id) if chapter_id else {}
        if chapter_id:
            prospective['chapter'] = await service.catalog.read_chapter(chapter_id, service.chapter_character_budget, chapter_offset)
        elif chapter_offset is not None:
            raise ValueError('读取正文片段时请指定章节')
        items = await service.read(targets, use_cache=True) if targets else []
        items = project_read_items(ctx, items, fields, prompt_offset)
        return {'targets': items, **prospective}
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


@creation_agent.tool
async def read_creation_history(ctx: RunContext[CreationAgentDeps], query: Annotated[str, Field(max_length=200)] = '',
                                before: Annotated[int | None, Field(gt=0)] = None,
                                archive_id: Annotated[int | None, Field(gt=0)] = None,
                                message_id: Annotated[int | None, Field(gt=0)] = None,
                                offset: Annotated[int, Field(ge=0)] = 0) -> dict:
    """分页回查本会话原始对话或压缩引用；历史不替代当前对象及权限。"""
    await crud_service(ctx).authorize()
    from services.creation_agent.retrieval import read_history
    try:
        return await read_history(ctx.deps.source_message, query=query, before=before,
                                  archive_id=archive_id, message_id=message_id, offset=offset, limit=ctx.deps.limits.context_page_characters)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


@creation_agent.tool(sequential=True)
async def patch_creation_prompts(ctx: RunContext[CreationAgentDeps], patches: list[CreationPromptPatch]) -> dict:
    """精确替换已读取设定或分镜的提示词片段；保留其余内容并返回可撤销回执。"""
    service = crud_service(ctx)
    operations = []
    for patch in patches:
        replacements = [item.model_dump() for item in patch.replacements]
        if patch.target.kind == 'scene':
            operations.append({
                'operation': 'update_scene',
                'scene_id': patch.target.id,
                'fields': {'prompt_replacements': replacements},
            })
        else:
            operations.append({
                'operation': 'update_setting',
                'target': patch.target.model_dump(),
                'fields': {'prompt_replacements': replacements},
            })
    try:
        return change_receipt(await service.apply(
            CreationChangeSet.model_validate({'operations': operations}),
            tool_call_id=ctx.tool_call_id or '',
        ))
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


@creation_agent.tool(sequential=True)
async def apply_creation_changes(ctx: RunContext[CreationAgentDeps], changes: CreationChangeSet) -> dict:
    """原子执行设定与分镜增删改；相关新增用 client_ref 引用；只返回已成功保存的回执。"""
    try:
        if not ctx.deps.tools_enabled:
            required = {operation.operation for operation in changes.operations}
            enabled = ctx.deps.enabled_capabilities
            allowed = all(
                operation in enabled
                or operation.startswith('create_') and 'create' in enabled
                or operation.startswith('update_') and 'update' in enabled
                for operation in required
            )
            if not allowed:
                raise ValueError('本轮未启用所需写入能力，请重新读取上下文并声明具体的新增、修改或删除能力')
        return change_receipt(await crud_service(ctx).apply(changes, tool_call_id=ctx.tool_call_id or ''))
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


@creation_agent.tool(sequential=True)
async def undo_creation_change(ctx: RunContext[CreationAgentDeps], change_id: Annotated[int, Field(gt=0)]) -> dict:
    """撤销本会话已保存的一组操作，不覆盖后续编辑或关联。"""
    service = crud_service(ctx)
    try:
        return change_receipt(await service.undo_for_run(change_id, ctx.deps.source_message))
    except ValueError as exc:
        raise ModelRetry(str(exc)) from None


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
