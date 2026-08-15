import asyncio
import logging
from collections.abc import Callable, Mapping

from openai import AsyncOpenAI

from services.ai_task_executor import BaseTaskHandler
from services.extraction.budget import ContextBudgetPolicy
from services.extraction.context import ExtractionContextLoader
from services.extraction.extractor import AssetExtractionGatewayError, AssetExtractor
from services.extraction.messages import ExtractionMessageBuilder
from services.extraction.persistence import AssetUpsertService
from services.extraction.prompt_preparation import AssetPromptPreparationService
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
        prompt_preparer: AssetPromptPreparationService | None = None,
        budget_policy_factory: Callable[
            [int | None], ContextBudgetPolicy
        ] = ContextBudgetPolicy,
        extractor_factory: Callable[..., AssetExtractor] = AssetExtractor,
    ) -> None:
        self.context_loader = context_loader or ExtractionContextLoader()
        self.message_builder = message_builder or ExtractionMessageBuilder()
        self.upsert_service = upsert_service or AssetUpsertService()
        self.prompt_preparer = prompt_preparer or AssetPromptPreparationService()
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
        extractor = self.extractor_factory(
            AsyncOpenAI(
                api_key=request_params["api_key"],
                base_url=request_params["base_url"],
            ),
            model=request_params["model"],
            supports_json_output=request_params.get(
                "supports_json_output",
                False,
            ),
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
            error_code = (
                error.error_code
                if isinstance(error, AssetExtractionGatewayError)
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
            if isinstance(error, AssetExtractionGatewayError):
                raise error from None
            raise AssetExtractionGatewayError() from None
        logger.info(
            "Extraction model call: novel_id=%s chapter_id=%s "
            "roles=%s call_status=succeeded",
            novel_id,
            chapter_id,
            formatted_message_roles,
        )

        prepared_result = self.prompt_preparer.prepare(
            result,
            prompt_language=prompt_language,
        )
        return await self.upsert_service.save_result(
            novel_id=novel_id,
            chapter_number=context.chapter.number,
            result=prepared_result,
        )
