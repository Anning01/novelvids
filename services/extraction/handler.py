import asyncio
import logging
from collections.abc import Callable, Mapping

from openai import AsyncOpenAI

from services.ai_task_executor import BaseTaskHandler
from services.extraction.budget import ContextBudgetPolicy
from services.extraction.context import ExtractionContextLoader
from services.extraction.extractor import AssetExtractionGatewayError, AssetExtractor, validate_required_design_assets
from services.extraction.messages import ExtractionMessageBuilder
from services.extraction.persistence import AssetUpsertService
from utils.prompt_language import normalize_prompt_language

logger = logging.getLogger(__name__)
EXPECTED_EXTRACTION_MESSAGE_ROLES = ("system", "user", "user", "user")
SAFE_EXTRACTION_MESSAGE_ROLES = frozenset(
    {"system", "user", "assistant", "tool", "developer"}
)
ASSET_EXTRACTION_MESSAGE_PROTOCOL_ERROR_CODE = (
    "asset_extraction_message_protocol_error"
)


def _derive_message_roles(messages: object) -> tuple[str, ...]:
    if not isinstance(messages, list):
        return ("invalid",)
    return tuple(
        role if isinstance(role, str) and role in SAFE_EXTRACTION_MESSAGE_ROLES
        else "invalid"
        for message in messages
        for role in (
            message.get("role") if isinstance(message, Mapping) else None,
        )
    )


def _format_message_roles(roles: tuple[str, ...]) -> str:
    return f"({','.join(roles)})"


class ExtractionTaskHandler(BaseTaskHandler):
    """提取任务处理器 - 人物/场景/物品提取并写入资产表。"""

    def __init__(
        self,
        *,
        context_loader: ExtractionContextLoader | None = None,
        message_builder: ExtractionMessageBuilder | None = None,
        upsert_service: AssetUpsertService | None = None,
        budget_policy_factory: Callable[
            [int | None], ContextBudgetPolicy
        ] = ContextBudgetPolicy,
        extractor_factory: Callable[..., AssetExtractor] = AssetExtractor,
    ) -> None:
        self.context_loader = context_loader or ExtractionContextLoader()
        self.message_builder = message_builder or ExtractionMessageBuilder()
        self.upsert_service = upsert_service or AssetUpsertService()
        self.budget_policy_factory = budget_policy_factory
        self.extractor_factory = extractor_factory

    async def execute(self, request_params: dict) -> dict:
        """
        request_params:
            chapter_id: int
            novel_id: int
            base_url: str
            api_key: str
            model: str
            concurrency: int（旧任务兼容字段；统一提取只调用模型一次）
            supports_json_output: bool
        """
        chapter_id = request_params["chapter_id"]
        novel_id = request_params["novel_id"]
        prompt_language = normalize_prompt_language(
            request_params.get("prompt_language")
        )
        context = await self.context_loader.load(
            novel_id=novel_id,
            chapter_id=chapter_id,
        )
        from services.creation_agent.skill_execution import current_execution
        from services.creation_agent.step_context import step_context
        execution = current_execution.get()
        reusable = None
        plan_context = await step_context(request_params) if execution else None
        targeted = bool(plan_context and plan_context.step.asset_scope == 'targeted')
        if plan_context and plan_context.step.mode == 'fill_missing' and not targeted:
            from services.extraction.reuse import extraction_reuse
            reusable = await extraction_reuse.find(execution, chapter_id)
            if reusable and reusable.complete:
                return {**reusable.summary, 'preserved_existing': True}
        if execution:
            from services.extraction.reuse import extraction_reuse
            await extraction_reuse.remember_inputs(execution, context)
        messages = self.message_builder.build(
            context,
            prompt_language=prompt_language,
        )
        message_roles = _derive_message_roles(messages)
        formatted_message_roles = _format_message_roles(message_roles)
        if message_roles != EXPECTED_EXTRACTION_MESSAGE_ROLES:
            logger.warning(
                "Extraction model call: novel_id=%s chapter_id=%s "
                "roles=%s call_status=failed "
                "error_type=AssetExtractionGatewayError error_code=%s",
                novel_id,
                chapter_id,
                formatted_message_roles,
                ASSET_EXTRACTION_MESSAGE_PROTOCOL_ERROR_CODE,
            )
            raise AssetExtractionGatewayError() from None

        report = self.budget_policy_factory(
            request_params.get("max_context_characters")
        ).validate(
            messages,
            asset_count=len(context.assets),
            chapter_characters=len(context.chapter.content),
        )
        logger.info(
            "Extraction context prepared: novel_id=%s chapter_id=%s "
            "assets=%s message_chars=%s total_chars=%s",
            novel_id,
            chapter_id,
            len(context.assets),
            report.message_characters,
            report.total_characters,
        )
        required_assets = () if targeted else tuple((asset.asset_type, asset.canonical_name) for asset in context.required_design_assets)
        if reusable:
            required_assets = tuple(dict.fromkeys((*required_assets, *reusable.required_assets)))
        extractor = self.extractor_factory(
            AsyncOpenAI(
                api_key=request_params["api_key"],
                base_url=request_params["base_url"],
            ),
            model=request_params["model"],
            prompt_language=prompt_language,
            supports_json_output=request_params.get(
                "supports_json_output",
                False,
            ),
            **({'required_assets': required_assets} if required_assets else {}),
            **({'initial_assets': reusable.accepted, 'required_variants': reusable.required_variants} if reusable else {}),
        )
        logger.info(
            "Extraction model call: novel_id=%s chapter_id=%s "
            "roles=%s call_status=started",
            novel_id,
            chapter_id,
            formatted_message_roles,
        )
        try:
            result = await extractor.extract(messages)
            validate_required_design_assets(result, required_assets)
            if getattr(extractor, 'targeted_assets', None) is not None:
                reusable = extractor.targeted_assets
        except asyncio.CancelledError:
            logger.warning(
                "Extraction model call: novel_id=%s chapter_id=%s "
                "roles=%s call_status=failed "
                "error_type=CancelledError error_code=cancelled",
                novel_id,
                chapter_id,
                formatted_message_roles,
            )
            raise
        except Exception as error:
            from services.extraction.validation import AssetExtractionValidationError
            error_code = (
                error.error_code
                if isinstance(error, (AssetExtractionGatewayError, AssetExtractionValidationError))
                else "unexpected_error"
            )
            logger.warning(
                "Extraction model call: novel_id=%s chapter_id=%s "
                "roles=%s call_status=failed error_type=%s error_code=%s",
                novel_id,
                chapter_id,
                formatted_message_roles,
                type(error).__name__,
                error_code,
            )
            if isinstance(error, (AssetExtractionGatewayError, AssetExtractionValidationError)):
                raise error from None
            raise AssetExtractionGatewayError() from None
        logger.info(
            "Extraction model call: novel_id=%s chapter_id=%s "
            "roles=%s call_status=succeeded",
            novel_id,
            chapter_id,
            formatted_message_roles,
        )

        from services.creation_agent.skill_execution import current_execution
        from services.creation_agent.operation_receipts import execute_step
        execution = current_execution.get()
        async def persist():
            from services.creation_agent.step_context import step_context, validate_step_inputs
            from services.creation_objects import project_write
            plan_context = await step_context(request_params)
            async with project_write(novel_id):
                await validate_step_inputs(request_params)
                from models.asset import Asset
                from models.asset_variant import AssetVariant
                from services.creation_agent.object_state import object_state, object_version, object_label, creation_version
                if reusable:
                    from utils.messages import localized_message
                    for key, version in reusable.repair_versions.items():
                        kind, identifier = key.split(':')
                        target = await (Asset if kind == 'asset' else AssetVariant).get_or_none(id=int(identifier))
                        if target is None or await object_version(target) != version:
                            raise ValueError(localized_message('待补全的设定已有新修改，已保留人工编辑，请重新核对'))
                before = {asset.id: await object_state(asset) for asset in await Asset.filter(novel_id=novel_id)} if plan_context else {}
                before_variants = {variant.id: await object_state(variant) for variant in
                    await AssetVariant.filter(asset__novel_id=novel_id)} if plan_context else {}
                options = {'preserve_existing': plan_context.step.mode == 'fill_missing', 'include_ids': True} if plan_context else {}
                if reusable:
                    options.update(repair_asset_ids=reusable.repair_asset_ids, repair_variant_ids=reusable.repair_variant_ids)
                summary = await self.upsert_service.save_result(novel_id=novel_id,
                    chapter_number=context.chapter.number, result=result, **options)
                if plan_context:
                    from models.creation_agent import PromptChange
                    from services.creation_agent.plan_sources import fingerprint
                    identifiers = [item['asset_id'] for group in summary.values() for item in group]
                    variant_ids = [item['variant_id'] for group in summary.values() for item in group if 'variant_id' in item]
                    summary['asset_ids'] = sorted(set(identifiers))
                    summary['variant_ids'] = sorted(set(variant_ids))
                    changes = []
                    for asset in await Asset.filter(id__in=identifiers):
                        previous, after = before.get(asset.id, {}), await object_state(asset)
                        if previous == after:
                            continue
                        changes.append({'kind': 'asset', 'target_id': asset.id, 'target_label': await object_label(asset),
                            'operation': 'update' if previous else 'create', 'before': previous, 'after': after,
                            'after_version': await object_version(asset), 'constraint_ids': [],
                            'recovery': {} if previous else {'creation_version': await creation_version(asset)}})
                    for variant in await AssetVariant.filter(id__in=variant_ids):
                        previous, after = before_variants.get(variant.id, {}), await object_state(variant)
                        if previous == after:
                            continue
                        changes.append({'kind': 'variant', 'target_id': variant.id, 'target_label': await object_label(variant),
                            'operation': 'update' if previous else 'create', 'before': previous, 'after': after,
                            'after_version': await object_version(variant), 'constraint_ids': [],
                            'recovery': {} if previous else {'creation_version': await creation_version(variant)}})
                    if changes:
                        await PromptChange.create(novel_id=novel_id, task_id=execution.params['task_id'],
                            tool_call_id='persist:assets', request_hash=fingerprint(result.model_dump()), changes=changes)
                return summary
        summary = await execute_step(execution.params['task_id'], 'persist:assets', persist, atomic=True) if execution else await persist()
        return {**summary, "token_usage": getattr(extractor, "last_usage", {}),
            **({'not_applied_reason': extractor.not_applied_reason} if getattr(extractor, 'not_applied_reason', None) else {})}
