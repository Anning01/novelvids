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
from services.creation_agent.model_boundary import RecordedAgentModel, main_request_count
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
    source = await AgentMessage.get_or_none(
        id=source_id, role="user", conversation__novel_id=params["novel_id"],
        conversation__team_id=params.get("team_id"),
    )
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
            messages = await AgentMessage.filter(
                conversation_id=self.message.conversation_id
            ).select_related("task")
            related = [
                m
                for m in messages
                if m.task_id == self.message.task_id
                or m.task.request_params.get("parent_task_id") == self.params["task_id"]
            ]
            if self.params.get('creation_plan_id'):
                # Include planning and every generation/check child, even across
                # private production conversations. One plan has one shared budget.
                plan_id = self.params['creation_plan_id']
                from models.agent_operation import AgentOperation
                root_ids = {plan_id, self.params.get('creation_run_id', plan_id)}
                receipts = await AgentOperation.filter(task_id__in=list(root_ids), key__startswith='submit:', state='completed')
                task_ids = root_ids | {row.result['task_id'] for row in receipts if row.result.get('task_id')}
                conversation_ids = await AgentMessage.filter(task_id__in=list(task_ids)).values_list('conversation_id', flat=True)
                candidates = await AgentMessage.filter(conversation_id__in=list(set(conversation_ids)), role='assistant').select_related('task')
                related = [m for m in candidates if str(m.task_id) == plan_id
                    or m.task.request_params.get('creation_plan_id') == plan_id
                    or m.task.request_params.get('parent_task_id') == plan_id]
            spent_requests = sum(main_request_count((m.usage or {}).get("calls", [])) for m in related)
            spent_tokens = sum(
                int((m.usage or {}).get("input_tokens", 0))
                + int((m.usage or {}).get("output_tokens", 0))
                for m in related
            )
            if (
                spent_requests >= limits.request_limit
                or spent_tokens >= limits.total_tokens_limit
            ):
                raise ValueError(localized_message("本次任务已达到总调用或用量上限"))
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
        agent = Agent(
            deps_type=SkillSnapshot,
            instructions=instructions(self.snapshot, self.language, skill) + (
                "\n" + additional_instructions if additional_instructions else ""
            ),
            output_type=output_type,
            retries=2,
        )

        @agent.tool
        def read_skill(ctx: RunContext[SkillSnapshot], name: str) -> str:
            """读取本次运行固定版本的技能；只接受技能清单中的名称。"""
            return ctx.deps.read(name)

        @agent.output_validator
        def validate_output(ctx: RunContext[SkillSnapshot], output):
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
            if skill in ("assets", "image"):
                styles = json.loads(self.snapshot.read("styles"))
                selected_style = styles.get(project.style_key, {})
                project_facts["image_style"] = (
                    (project.custom_style_prompt or "").strip()
                    or selected_style.get("image", "")
                )
            request_facts = {
                "input": facts,
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
                external_started=lambda: bool(recorded.calls),
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
