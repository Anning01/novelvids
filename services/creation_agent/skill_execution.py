"""Shared skill/model boundary for interactive and button-driven creation."""

from contextvars import ContextVar
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
import json
from fastapi import HTTPException
from utils.messages import localized_message
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits
from models.creation_agent import AgentMessage
from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills, task_facts, creative_requirements
from services.creation_agent.model_boundary import RecordedAgentModel
from utils.enums import AiTaskTypeEnum

WORKFLOW_VERSION = "agent-skills-v1"


async def require_agent(team_id=None, model_id=None):
    from services.creation_agent.sessions import agent_configuration
    from services.model_resolution import resolve_scope_configs
    from config import settings

    limits = await agent_configuration()
    if not limits.enabled:
        raise HTTPException(409, localized_message("创作助手尚未启用"))
    models = await resolve_scope_configs(
        AiTaskTypeEnum.creation_agent.value,
        team_id if settings.AUTH_ENABLED else None,
        capability_filter=lambda config: config.supports_tool_calls,
    )
    chosen = next(
        (item for item in models if model_id is None or item.id == model_id), None
    )
    if chosen is None:
        raise HTTPException(
            422, localized_message("请配置已启用且支持工具调用的创作助手模型")
        )
    return chosen, limits


async def prepare_workflow(params: dict) -> dict:
    chosen, limits = await require_agent(
        params.get("team_id"), params.get("assistant_model_config_id")
    )
    if params.get("workflow_version") == WORKFLOW_VERSION:
        SkillSnapshot.model_validate(params["skill_snapshot"])
        return dict(params)
    from services.creation_agent.submissions import submission

    parent = current_execution.get()
    inherited = {}
    if parent:
        inherited = {
            key: parent.params[key]
            for key in (
                "prompt_language",
                "skill_snapshot",
                "assistant_model_config_id",
                "agent_configuration",
            )
        }
        inherited["origin_run_id"] = parent.params["task_id"]
        source_id = parent.params.get("instruction_message_id")
        if source_id is None:
            source = await AgentMessage.get_or_none(
                task_id=parent.params["task_id"], role="user",
                task__task_type=AiTaskTypeEnum.creation_agent.value,
            )
            source_id = source.id if source else None
        if source_id is not None:
            inherited["instruction_message_id"] = source_id
        for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id'):
            if key in parent.params:
                inherited[key] = parent.params[key]
    return {
        **params,
        **(submission.get() or {}),
        "workflow_version": WORKFLOW_VERSION,
        "assistant_model_config_id": chosen.id,
        "agent_configuration": limits.model_dump(),
        "skill_snapshot": snapshot_skills(),
        **inherited,
    }


async def user_instruction(params: dict) -> str:
    source_id = params.get("instruction_message_id")
    if source_id is None:
        return ""
    query = AgentMessage.filter(
        id=source_id, role="user", conversation__novel_id=params["novel_id"],
        conversation__created_by=params.get("user_id"),
    )
    # Global administrator runs have no selected team; their project can have one.
    # Project access is authorized by before_request, private text by its owner.
    if params.get("team_id") is not None:
        query = query.filter(conversation__team_id=params["team_id"])
    source = await query.first()
    if source is None:
        raise ValueError(localized_message("原始创作要求已不可用，请重新提交任务"))
    return source.content


@dataclass
class SkillExecution:
    params: dict
    message: AgentMessage
    before_request: Callable[[], Awaitable[object]]

    @property
    def snapshot(self):
        return SkillSnapshot.model_validate(self.params["skill_snapshot"])

    @property
    def language(self):
        return self.params.get("prompt_language", "en")

    async def generate(
        self, skill: str, facts: object, output_type: type[BaseModel], **options,
    ):
        if skill != 'authorization':
            await user_instruction(self.params)
        from services.creation_agent.step_context import step_context
        context = await step_context(self.params) if skill in {'assets', 'storyboard', 'image', 'video'} else None
        if context and (context.requirements or context.constraints or self.params.get('creation_plan_id') != self.params['task_id']):
            from services.creation_agent.creative_checks import generate_checked
            return await generate_checked(self, skill, facts, output_type, options, context)
        return await self._generate(skill, facts, output_type, **options)

    async def _generate(
        self,
        skill: str,
        facts: object,
        output_type: type[BaseModel],
        *,
        model_config=None,
        media=None,
        additional_instructions: str = "",
        output_validator: Callable[[BaseModel], Awaitable[None]] | None = None,
    ):
        from services.creation_agent.handler import configured_model

        chosen, limits = await require_agent(
            self.params.get("team_id"), self.params["assistant_model_config_id"]
        )
        chosen = model_config or chosen
        if not chosen.is_active:
            raise ValueError(localized_message("模型已停用"))
        from schemas.creation_agent import AgentConfiguration

        limits = AgentConfiguration.model_validate(self.params["agent_configuration"])
        from models.ai_task import AiTask
        from services.creation_agent.operation_receipts import execute_step
        from services.billing.recorder import record_ai_task_usage
        from uuid import uuid5, UUID
        from utils.enums import TaskStatusEnum

        segment = str(facts.get("segment", "")) if isinstance(facts, dict) else ""
        key = f"model:{skill}:{output_type.__name__}:{segment}"
        child_id = uuid5(UUID(self.params["task_id"]), key)
        child, _ = await AiTask.get_or_create(
            id=child_id,
            defaults={
                "task_type": AiTaskTypeEnum.creation_agent.value,
                "status": TaskStatusEnum.running.value,
                "request_params": {
                    **self.params,
                    "parent_task_id": self.params["task_id"],
                    "model_config_id": chosen.id,
                    "assistant_model_config_id": self.params[
                        "assistant_model_config_id"
                    ],
                },
            },
        )
        child_message = await AgentMessage.get_or_none(
            task_id=child.id, role="assistant"
        )
        if child_message is None:
            child_message = await AgentMessage.create(
                conversation_id=self.message.conversation_id,
                task=child,
                request_id=child.id,
                request_hash=str(child.id),
                role="assistant",
                run_input={"internal_production_step": True},
                model_snapshot={
                    "id": chosen.id,
                    "name": chosen.name,
                    "model": chosen.model,
                    "scope": chosen.scope,
                    "pricing": chosen.pricing,
                },
            )
        model = configured_model(chosen, limits)

        async def validate_call():
            await self.before_request()
            from services.balance import ensure_solvent

            await ensure_solvent(self.params.get("team_id"), self.params.get("user_id"))
            if model_config is not None:
                from controllers.config import ai_model_config_controller

                available = await ai_model_config_controller.get_active(
                    AiTaskTypeEnum.remake_decomposition.value,
                    model_config.id,
                    team_id=self.params.get("team_id"),
                )
                if not available.supports_tool_calls:
                    raise ValueError(localized_message("视频理解模型需要支持工具调用"))

        from services.creation_agent.event_log import agent_event_log
        from services.task_signals import task_signals
        from datetime import datetime, timezone

        async def report_activity(call):
            label = {
                "authorization": "理解生成要求", "story": "分析故事", "assets": "提取本章资产",
                "image": "准备图片提示词", "storyboard": "生成分镜", "remake": "分析参考视频",
                "video": "准备视频提示词",
            }.get(skill, "处理创作要求")
            item = {
                "id": f"model:{child.id}:{call['index']}", "kind": "status", "label": label,
                "status": "running" if call["status"] == "in_progress" else call["status"],
                "started_at": call["started_at"], "finished_at": call.get("finished_at"),
            }
            event = {"type": "CUSTOM", "name": "agent_activity", "value": item,
                     "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)}
            seq = await agent_event_log.start(child_message)
            await agent_event_log.append(child_message.id, [event], seq)
            await task_signals.publish(str(self.message.task_id))

        recorded = RecordedAgentModel(
            model,
            message=child_message,
            before_request=validate_call,
            max_characters=limits.context_character_limit(chosen.max_context_characters),
            request_limit=limits.request_limit,
            total_tokens_limit=limits.total_tokens_limit,
            limits=limits,
            on_activity=report_activity,
        )
        request_aspect_ratio = "16:9"
        from services.storyboard.speech_timing import StoryboardSpeechValidator
        speech_validator = StoryboardSpeechValidator(self.snapshot) if skill == "storyboard" else None
        if skill in {'storyboard', 'video'}:
            from prompts.creation_plan import resolved_storyboard_resources_instructions
            additional_instructions += '\n' + resolved_storyboard_resources_instructions(self.language)
        agent = Agent(
            deps_type=SkillSnapshot,
            instructions=instructions(self.snapshot, self.language, skill) + (
                "\n" + additional_instructions if additional_instructions else ""
            ),
            output_type=output_type,
            retries=2,
        )

        def read_skill(ctx: RunContext[SkillSnapshot], name: str) -> str:
            """读取本次运行固定版本的技能；只接受技能清单中的名称。"""
            return ctx.deps.read(name)

        # These phases already receive their full rules and evidence. Additional
        # skill lookups only repeat context and consume the user's call budget.
        if skill not in {'planning_request', 'source_reading', 'creative_check', 'storyboard', 'video'}:
            agent.tool(read_skill)

        @agent.output_validator
        async def validate_output(ctx: RunContext[SkillSnapshot], output):
            if skill == 'source_reading' and isinstance(facts, dict) and facts.get('reference_protocol') == 2:
                from services.creation_agent.source_references import resolve_reading
                from pydantic_ai import ModelRetry
                try:
                    output = resolve_reading(output, facts, require_paragraphs=True)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if skill == "assets":
                from pydantic_ai import ModelRetry
                from services.extraction.extractor import validate_asset_prompt_contract

                try:
                    validate_asset_prompt_contract(output, ctx.deps, self.language, request_aspect_ratio)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if skill == "image" and isinstance(facts, dict) and facts.get("asset_type") in {1, 2, 3}:
                from pydantic_ai import ModelRetry
                from prompts.creation_standards import ASSET_PROMPT_KINDS
                from prompts.reference import GROUP_PORTRAIT
                from services.extraction.extractor import validate_asset_design

                kind = ('group' if facts['asset_type'] == 1 and facts.get('reference_layout') == GROUP_PORTRAIT
                        else ASSET_PROMPT_KINDS[facts['asset_type']])
                try:
                    validate_asset_design(output.prompt, kind, ctx.deps, self.language, request_aspect_ratio)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if skill == "storyboard" and hasattr(output, "shots"):
                from pydantic_ai import ModelRetry
                from services.storyboard.validation import validate_skill_storyboard_timing, validate_storyboard_duration

                try:
                    if speech_validator is not None:
                        speech_validator.validate(output.shots)
                    for shot in output.shots:
                        validate_storyboard_duration(shot, self.params.get("shot_duration_range"))
                        if "storyboard_contract" in ctx.deps.contents:
                            validate_skill_storyboard_timing(shot)
                    source_facts = facts
                    while isinstance(source_facts, dict) and 'original_input' in source_facts:
                        source_facts = source_facts['original_input']
                    if isinstance(source_facts, dict) and 'entities' in source_facts and 'storyboard_contract' in ctx.deps.contents:
                        from schemas.scene import SceneEntity
                        from services.storyboard.validation import prepare_skill_storyboard
                        from services.storyboard.strategies import storyboard_strategy_factory
                        from services.creation_agent.prompt_edits import validate_prompt_dependencies
                        entities = [SceneEntity.model_validate(item) for item in source_facts['entities']]
                        strategy = storyboard_strategy_factory.resolve(source_facts.get('strategy'))
                        prepared = prepare_skill_storyboard(output, ctx.deps, self.language, entities, strategy.key)
                        for shot in prepared.shots:
                            validate_prompt_dependencies(shot.prompt, entities)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if output_validator:
                from pydantic_ai import ModelRetry
                try:
                    await output_validator(output)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            return output

        async def invoke():
            nonlocal request_aspect_ratio
            from models.novel import Novel

            project = await Novel.get(id=self.params["novel_id"])
            request_aspect_ratio = project.aspect_ratio or "16:9"
            project_facts = {
                "name": project.name,
                "style_key": project.style_key,
                "custom_style_prompt": project.custom_style_prompt,
                "aspect_ratio": project.aspect_ratio,
                "storyboard_strategy": project.storyboard_strategy,
            }
            if skill in ("assets", "image", "storyboard", "video"):
                styles = json.loads(self.snapshot.read("styles"))
                selected_style = styles.get(project.style_key, {})
                style_kind = 'image' if skill in {'assets', 'image'} else 'video'
                project_facts[style_kind + '_style'] = (
                    (project.custom_style_prompt or "").strip()
                    or selected_style.get(style_kind, "")
                )
            if skill in {'storyboard', 'video'}:
                from services.storyboard.strategies import storyboard_strategy_factory
                strategy = storyboard_strategy_factory.resolve(project.storyboard_strategy)
                project_facts['storyboard_rules'] = json.loads(self.snapshot.read('strategies'))[strategy.key]
            request_facts = {
                "input": ({key: value for key, value in facts.items() if key != 'content'}
                    if skill == 'source_reading' and isinstance(facts, dict) and facts.get('reference_protocol') == 2 else facts),
                "project": project_facts,
                "parameters": {
                    key: self.params[key]
                    for key in (
                        "aspect_ratio",
                        "resolution",
                        "duration",
                        "reference_images",
                    )
                    if key in self.params
                },
            }
            from services.creation_agent.step_context import step_context
            context = await step_context(self.params) if skill in {'assets', 'storyboard', 'image', 'video'} else None
            if context:
                request_facts['step_context'] = context.model_dump(mode='json')
            if skill == "authorization":
                request_facts = {"input": facts}
            user_input = (
                [task_facts(request_facts), *media]
                if media
                else task_facts(request_facts)
            )
            if context:
                if context.requirements or context.constraints or self.params.get('creation_plan_id') != self.params['task_id']:
                    from prompts.creation_plan import step_requirements
                    user_input = [task_facts(request_facts), step_requirements(self.language), *(media or [])]
            elif skill != "authorization":
                requirement = await user_instruction(self.params)
                if requirement:
                    user_input = [
                        task_facts(request_facts),
                        creative_requirements(requirement, self.language),
                        *(media or []),
                    ]
            result = await agent.run(
                user_input,
                deps=self.snapshot,
                model=recorded,
                usage_limits=UsageLimits(
                    request_limit=limits.request_limit,
                    tool_calls_limit=limits.tool_calls_limit,
                    total_tokens_limit=limits.total_tokens_limit,
                ),
                model_settings={
                    "max_tokens": min(
                        limits.max_output_tokens,
                        chosen.max_tokens or limits.max_output_tokens,
                    )
                },
            )
            await AgentMessage.filter(id=child_message.id).update(
                native_messages=_audit_messages(result.new_messages())
            )
            return result.output.model_dump(mode="json")

        try:
            payload = await execute_step(
                self.params["task_id"], key, invoke, external=True,
                # A complete response rejected by output validation is a known
                # failure. Only interrupted/failed requests remain uncertain.
                external_started=lambda: bool(recorded.calls) and any(call['status'] != 'completed' for call in recorded.calls),
            )
            child.status = TaskStatusEnum.completed.value
            child.response_data = payload
            await child.save(update_fields=["status", "response_data"])
            return output_type.model_validate(payload)
        except BaseException:
            child.status = TaskStatusEnum.failed.value
            await child.save(update_fields=["status"])
            raise
        finally:
            try:
                await record_ai_task_usage(child, result=child.response_data)
            except Exception:
                await AiTask.filter(id=child.id).update(stage="billing_pending")
            finally:
                await model.client.close()


current_execution: ContextVar[SkillExecution | None] = ContextVar(
    "skill_execution", default=None
)


def _audit_messages(messages):
    """Keep media identities in model-step history without duplicating uploaded bytes."""
    from dataclasses import replace
    import hashlib
    from pydantic_ai.messages import (
        BinaryContent,
        ModelRequest,
        ModelMessagesTypeAdapter,
        UserPromptPart,
    )

    projected = []
    for message in messages:
        if isinstance(message, ModelRequest):
            parts = []
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, list):
                    content = [
                        f"[{item.media_type}; bytes={len(item.data)}; sha256={hashlib.sha256(item.data).hexdigest()}]"
                        if isinstance(item, BinaryContent)
                        else item
                        for item in part.content
                    ]
                    part = replace(part, content=content)
                parts.append(part)
            message = replace(message, parts=parts)
        projected.append(message)
    return json.loads(ModelMessagesTypeAdapter.dump_json(projected))
