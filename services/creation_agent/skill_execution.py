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
from prompts.skill_pack import SkillSnapshot, instructions, snapshot_skills, task_facts
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
    return {
        **params,
        **(submission.get() or {}),
        "workflow_version": WORKFLOW_VERSION,
        "assistant_model_config_id": chosen.id,
        "agent_configuration": limits.model_dump(),
        "skill_snapshot": snapshot_skills(),
        **inherited,
    }


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
        self,
        skill: str,
        facts: object,
        output_type: type[BaseModel],
        *,
        model_config=None,
        media=None,
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
            spent_requests = sum(len((m.usage or {}).get("calls", [])) for m in related)
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

        recorded = RecordedAgentModel(
            model,
            message=child_message,
            before_request=validate_call,
            max_characters=limits.context_character_limit(chosen.max_context_characters),
            request_limit=limits.request_limit,
            total_tokens_limit=limits.total_tokens_limit,
            limits=limits,
        )
        agent = Agent(
            deps_type=SkillSnapshot,
            instructions=instructions(self.snapshot, self.language, skill),
            output_type=output_type,
            retries=2,
        )

        @agent.tool
        def read_skill(ctx: RunContext[SkillSnapshot], name: str) -> str:
            """读取本次运行固定版本的技能；只接受技能清单中的名称。"""
            return ctx.deps.read(name)

        @agent.output_validator
        def validate_output(ctx: RunContext[SkillSnapshot], output):
            if skill == "storyboard" and hasattr(output, "shots"):
                from pydantic_ai import ModelRetry
                from services.storyboard.validation import validate_skill_storyboard_timing

                try:
                    if "storyboard_contract" in ctx.deps.contents:
                        for shot in output.shots:
                            validate_skill_storyboard_timing(shot)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            return output

        async def invoke():
            from models.novel import Novel

            project = await Novel.get(id=self.params["novel_id"])
            project_facts = {
                "name": project.name,
                "style_key": project.style_key,
                "custom_style_prompt": project.custom_style_prompt,
                "aspect_ratio": project.aspect_ratio,
                "storyboard_strategy": project.storyboard_strategy,
            }
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
            if skill == "authorization":
                request_facts = {"input": facts}
            user_input = (
                [task_facts(request_facts), *media]
                if media
                else task_facts(request_facts)
            )
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
