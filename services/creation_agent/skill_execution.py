"""Shared skill/model boundary for interactive and button-driven creation."""

from contextvars import ContextVar
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
import json
from fastapi import HTTPException
from utils.messages import localized_message
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, PromptedOutput
from pydantic_ai.usage import UsageLimits
from pydantic_ai.exceptions import ModelHTTPError
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
    if "prompt_language" not in params:
        from services.language import generation_language

        params = {**params, "prompt_language": await generation_language()}
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
                "skill_snapshot",
                "assistant_model_config_id",
                "agent_configuration",
            )
        }
        inherited["prompt_language"] = parent.language
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
        for key in ('video_optimizer', 'conversation_id', 'agent_runtime', 'creation_plan_id', 'creation_step_id', 'creation_run_id', 'recovery_root_task_id'):
            if key in parent.params:
                inherited[key] = parent.params[key]
    from services.creation_agent.video_optimizer import project_optimizer
    if params.get('novel_id'):
        from models.novel import Novel
        project = await Novel.get(id=params['novel_id'])
        duration_range = params.get('shot_duration_range') or [1, project.shot_duration_max]
        params = {**params, 'shot_duration_range': [duration_range[0], min(duration_range[1], project.shot_duration_max)]}
    optimizer = inherited.get('video_optimizer') or params.get('video_optimizer') or (await project_optimizer(params['novel_id'], params.get('team_id')) if params.get('novel_id') else {'mode': 'generic'})
    return {
        'video_optimizer': optimizer,
        **params,
        **(submission.get() or {}),
        "workflow_version": WORKFLOW_VERSION,
        "agent_runtime": params.get("agent_runtime", limits.runtime),
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

    async def repair_root(self):
        from services.creation_agent.reliability import recovery_root
        return await recovery_root(self.params)

    async def claim_repair(self, stage, code):
        from services.creation_agent.reliability import claim_repair, failure_checkpoint
        root = await self.repair_root()
        issues = [{'tool': stage, 'code': code}]
        await failure_checkpoint(root, self.message.id, issues, stage=stage)
        await claim_repair(root, issues)

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
        initial_assets: BaseModel | None = None,
        asset_scope: tuple[tuple[int, str], ...] = (),
        activity_label: str | None = None,
    ):
        from services.creation_agent.handler import configured_model
        from schemas.agent_workflow import RemakeShot

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
        from models.agent_operation import AgentOperation
        from services.creation_agent.plan_sources import fingerprint
        stable_facts = dict(facts) if isinstance(facts, dict) else facts
        if isinstance(stable_facts, dict) and isinstance(stable_facts.get('selection'), dict):
            stable_facts['selection'] = {k: v for k, v in stable_facts['selection'].items()
                                       if k not in {'request_id', 'resume_from_task_id'}}
        input_key = 'model-input:' + fingerprint(key)
        revision = fingerprint([skill, stable_facts, self.snapshot.revision, self.language, chosen.id,
                                output_type.model_json_schema(), additional_instructions,
                                *([initial_assets.model_dump(mode='json')] if initial_assets is not None else [])])
        if asset_scope:
            revision = fingerprint([revision, asset_scope])
        saved_input, _ = await AgentOperation.get_or_create(task_id=self.params['task_id'], key=input_key,
            defaults={'state': 'completed', 'result': {'revision': revision}})
        if saved_input.result['revision'] != revision:
            raise ValueError(localized_message('候选的输入或协议已变化，请重新规划'))
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
            from services.creation_agent.run_recovery import checkpoint_inputs
            await checkpoint_inputs(self.params)
            from services.balance import ensure_solvent

            await ensure_solvent(self.params.get("team_id"), self.params.get("user_id"))
            if model_config is not None:
                from controllers.config import ai_model_config_controller

                available = await ai_model_config_controller.get_active(
                    AiTaskTypeEnum.remake_decomposition.value,
                    model_config.id,
                    team_id=self.params.get("team_id"),
                )
                if not (available.supports_tool_calls or skill == 'remake' and available.supports_json_output):
                    raise ValueError(localized_message("视频理解模型需要支持工具调用"))

        from services.creation_agent.event_log import agent_event_log
        from services.task_signals import task_signals
        from datetime import datetime, timezone

        async def report_activity(call):
            from services.creation_agent.skill_stream import skill_activity_label
            label = activity_label or skill_activity_label(skill, self.language)
            item = {
                "id": f"model:{child.id}:{call['index']}", "kind": "status", "label": label,
                "status": "running" if call["status"] == "in_progress" else call["status"],
                "started_at": call["started_at"], "finished_at": call.get("finished_at"),
            }
            event = {"type": "CUSTOM", "name": "agent_activity", "value": item,
                     "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000)}
            seq = await agent_event_log.start(child_message)
            await agent_event_log.append(child_message.id, [event], seq)
            from services.creation_agent.skill_stream import forward_skill_event
            await forward_skill_event(event)
            await task_signals.publish(str(self.message.task_id))

        from services.creation_agent.skill_stream import SkillRunActivity

        tool_activity = SkillRunActivity(child_message, str(self.message.task_id))

        recorded = RecordedAgentModel(
            model,
            message=child_message,
            before_request=validate_call,
            max_characters=limits.context_character_limit(chosen.max_context_characters),
            request_limit=limits.request_limit,
            total_tokens_limit=limits.total_tokens_limit,
            limits=limits,
            on_activity=report_activity,
            # Each detected clip is a separate model step with its own durable retry allowance.
            repair_root=str(child.id) if skill == "remake" and output_type is RemakeShot else await self.repair_root(),
            stage=skill,
            repair_attempts=2 if skill == "remake" else 1,
        )
        request_aspect_ratio = "16:9"
        from services.storyboard.candidates import StoryboardCandidateValidator
        storyboard_candidates = (StoryboardCandidateValidator(output_type, self.snapshot, self.language,
            facts.get('shot_duration_range', self.params.get('shot_duration_range')) if isinstance(facts, dict) else self.params.get('shot_duration_range'), facts)
            if skill == 'storyboard' and 'shots' in output_type.model_fields else None)
        storyboard_checkpoint = None
        if storyboard_candidates:
            from models.agent_operation import AgentOperation
            saved = await AgentOperation.get_or_none(task_id=self.params['task_id'], key=f'candidate:storyboard:{segment}', state='completed')
            if saved:
                storyboard_checkpoint = saved.result
                storyboard_candidates.restore(storyboard_checkpoint)
        if skill in {'storyboard', 'video'}:
            from prompts.creation_plan import resolved_storyboard_resources_instructions
            additional_instructions += '\n' + resolved_storyboard_resources_instructions(self.language)
        from services.extraction.validation import AssetCandidateValidator, AssetExtractionValidationError
        asset_candidates = AssetCandidateValidator(output_type, asset_scope) if skill == 'assets' else None
        agent_output = (storyboard_candidates.draft_type if storyboard_candidates else
                        asset_candidates.draft_type if asset_candidates else output_type)
        if chosen.supports_json_output:
            agent_output = PromptedOutput(agent_output)
        agent = Agent(
            deps_type=SkillSnapshot,
            instructions=instructions(self.snapshot, self.language, skill,
                output_kind=facts.get('output_kind') if isinstance(facts, dict) else None) + (
                "\n" + additional_instructions if additional_instructions else ""
            ),
            output_type=agent_output,
            retries=0 if skill == 'screenplay' else 2,
        )

        def read_skill(ctx: RunContext[SkillSnapshot], name: str) -> str:
            """读取本次运行固定版本的技能；只接受技能清单中的名称。"""
            return ctx.deps.read(name)

        # These phases already receive their full rules and evidence. Additional
        # skill lookups only repeat context and consume the user's call budget.
        if skill not in {'planning_request', 'source_reading', 'creative_check', 'screenplay', 'storyboard', 'video', 'structured', 'remake'}:
            agent.tool(read_skill)

        asset_checkpoint = None
        if asset_candidates:
            from models.agent_operation import AgentOperation
            saved = await AgentOperation.get_or_none(task_id=self.params['task_id'], key=f'candidate:assets:{segment}', state='completed')
            if saved:
                asset_checkpoint = saved.result
                asset_candidates.restore(asset_checkpoint, output_type)

        @agent.output_validator
        async def validate_output(ctx: RunContext[SkillSnapshot], output):
            if skill == 'remake' and isinstance(facts, dict) and facts.get('output_kind') == 'global_key_assets':
                from services.remake.asset_validation import render_remake_assets
                from pydantic_ai import ModelRetry
                try:
                    rendered = render_remake_assets(output.model_dump(), ctx.deps, self.language, request_aspect_ratio)
                    output = type(output).model_validate(rendered)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if skill == 'source_reading' and isinstance(facts, dict) and facts.get('reference_protocol') == 2:
                from services.creation_agent.source_references import resolve_reading
                from pydantic_ai import ModelRetry
                try:
                    output = resolve_reading(output, facts, require_paragraphs=True)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if skill == "assets":
                from pydantic_ai import ModelRetry
                from models.agent_operation import AgentOperation
                from prompts.extraction import render_asset_repair

                attempted = output.model_dump(mode='json', warnings=False)
                output = asset_candidates.merge(output)
                if output_validator:
                    try:
                        await output_validator(output)
                    except ValueError as error:
                        asset_candidates.issues.append(str(error))
                await AgentOperation.update_or_create(task_id=self.params['task_id'], key=f'candidate:assets:{segment}',
                    defaults={'state': 'completed', 'result': {'attempted': attempted,
                        'accepted': output.model_dump(mode='json'), 'issues': asset_candidates.issues,
                        'pending': [[list(key), issue] for key, issue in asset_candidates.pending.items()]}})
                if asset_candidates.issues:
                    raise ModelRetry(render_asset_repair(self.language, asset_candidates.names(), asset_candidates.issues))
            if skill == "image" and isinstance(facts, dict) and facts.get("asset_type") in {1, 2, 3}:
                from pydantic_ai import ModelRetry
                from services.extraction.extractor import validate_asset_design

                try:
                    validate_asset_design(output.prompt)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            if storyboard_candidates:
                from pydantic_ai import ModelRetry
                from models.agent_operation import AgentOperation
                from prompts.storyboard_repair import structural_repair
                merged, checkpoint = storyboard_candidates.merge(output)
                # JSON object keys must also work with the ORM's optional accelerated encoder.
                await AgentOperation.update_or_create(task_id=self.params['task_id'], key=f'candidate:storyboard:{segment}',
                    defaults={'state': 'completed', 'result': json.loads(json.dumps(checkpoint))})
                if merged is None:
                    raise ModelRetry(structural_repair(self.language, checkpoint))
                output = merged
            if output_validator and skill != 'assets':
                from pydantic_ai import ModelRetry
                try:
                    await output_validator(output)
                except ValueError as error:
                    raise ModelRetry(str(error)) from None
            return output

        request_rejected = False

        async def invoke():
            nonlocal request_aspect_ratio, request_rejected
            # A resumed child may still carry its previous failure. Only a claimed
            # step becomes running; cached completed steps never change state.
            child.status = TaskStatusEnum.running.value
            await child.save(update_fields=['status'])
            if storyboard_checkpoint and not storyboard_checkpoint['pending'] and not storyboard_checkpoint['protocol_errors']:
                return storyboard_candidates.result().model_dump(mode='json')
            if asset_checkpoint and not asset_checkpoint['issues']:
                return asset_checkpoint['accepted']
            from models.novel import Novel

            project = await Novel.get(id=self.params["novel_id"])
            request_aspect_ratio = project.aspect_ratio or "16:9"
            if initial_assets is not None and asset_candidates and not asset_checkpoint:
                asset_candidates.merge(initial_assets)
            from prompts.project_settings import audiovisual_guidance
            project_facts = {
                "name": project.name,
                "audiovisual_guidance": audiovisual_guidance(project.audiovisual_guidance, self.language),
                "shot_duration_max": project.shot_duration_max,
                "storyboard_enabled": project.storyboard_enabled,
                "style_key": project.style_key,
                "custom_style_prompt": project.custom_style_prompt,
                "aspect_ratio": project.aspect_ratio,
                "storyboard_strategy": project.storyboard_strategy,
            }
            if skill in ("assets", "image", "storyboard", "video", "remake"):
                styles = json.loads(self.snapshot.read("styles"))
                selected_style = styles.get(project.style_key, {})
                style_kind = 'image' if skill in {'assets', 'image', 'remake'} else 'video'
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
            if storyboard_candidates and isinstance(facts, dict) and 'storyboard_repair' in facts:
                request_facts['input'] = {key: value for key, value in facts.items() if key != 'storyboard_repair'}
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
            from pydantic_ai import capture_run_messages

            if storyboard_checkpoint:
                from prompts.storyboard_repair import structural_repair
                checkpoint = {**storyboard_checkpoint,
                    'candidates': {int(key): value for key, value in storyboard_checkpoint['candidates'].items()},
                    'pending': {int(key): value for key, value in storyboard_checkpoint['pending'].items()}}
                user_input = [*(user_input if isinstance(user_input, list) else [user_input]), structural_repair(self.language, checkpoint)]
            if asset_checkpoint and asset_checkpoint['issues']:
                from prompts.extraction import render_asset_repair
                user_input = [*(user_input if isinstance(user_input, list) else [user_input]),
                    render_asset_repair(self.language, asset_candidates.names(), asset_candidates.issues)]
            receipt = await AgentOperation.get(task_id=self.params['task_id'], key=key)
            if storyboard_checkpoint or asset_checkpoint or receipt.result.get('recovered_failure'):
                await self.claim_repair(skill, 'saved_candidate')

            with capture_run_messages() as run_messages:
                try:
                    result = await agent.run(
                        user_input,
                        deps=self.snapshot,
                        model=recorded,
                        event_stream_handler=tool_activity,
                        usage_limits=UsageLimits(
                            request_limit=limits.request_limit,
                            tool_calls_limit=limits.tool_calls_limit,
                            total_tokens_limit=limits.total_tokens_limit,
                        ),
                        model_settings=limits.output_model_settings(chosen.max_tokens),
                    )
                except ModelHTTPError as error:
                    request_rejected = 400 <= error.status_code < 500 and error.status_code not in {408, 409}
                    raise
                finally:
                    await AgentMessage.filter(id=child_message.id).update(
                        native_messages=_audit_messages(run_messages)
                    )
            return result.output.model_dump(mode="json")

        try:
            payload = await execute_step(
                self.params["task_id"], key, invoke, external=True,
                # A complete response rejected by output validation is a known
                # failure. Only interrupted/failed requests remain uncertain.
                external_started=lambda: not request_rejected and bool(recorded.calls) and any(call['status'] != 'completed' for call in recorded.calls),
            )
            child.status = TaskStatusEnum.completed.value
            child.response_data = payload
            await child.save(update_fields=["status", "response_data"])
            return output_type.model_validate(payload)
        except BaseException as error:
            child.status = TaskStatusEnum.failed.value
            await child.save(update_fields=["status"])
            from pydantic_ai.exceptions import UnexpectedModelBehavior
            from services.creation_agent.reliability import RepairExhausted
            if isinstance(error, (UnexpectedModelBehavior, RepairExhausted)) and asset_candidates and asset_candidates.issues:
                raise AssetExtractionValidationError(asset_candidates.issues) from error
            if isinstance(error, (UnexpectedModelBehavior, RepairExhausted)) and storyboard_candidates and storyboard_candidates.pending:
                details = '；'.join(f'{number}: {" / ".join(issues)}' for number, issues in storyboard_candidates.pending.items())
                raise ValueError(localized_message('部分分镜修正仍未通过，已保留合格镜头与候选：{p0}', p0=details)) from error
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
        VideoUrl,
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
                        else f"[{item.media_type}; temporary video]" if isinstance(item, VideoUrl)
                        else item
                        for item in part.content
                    ]
                    part = replace(part, content=content)
                parts.append(part)
            message = replace(message, parts=parts)
        projected.append(message)
    return json.loads(ModelMessagesTypeAdapter.dump_json(projected, fallback=str))
