"""Safe, user-facing reasons for failed extraction requests."""
from openai import APIStatusError
from pydantic_ai.exceptions import ModelHTTPError

from models.agent_operation import AgentOperation
from services.creation_agent.model_boundary import ModelOutputLimitError
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message

GENERIC_CODE = "asset_extraction_gateway_error"
GENERIC_MESSAGE = f"资产提取模型调用失败（错误代码：{GENERIC_CODE}）"
OUTPUT_LIMIT = "模型单次输出达到上限，资产提取未完成。请缩短本章内容，或选择支持更长输出的模型后重试。"
BALANCE = "模型服务返回可用额度不足，请检查对应账户的余额和限额。"
AUTHENTICATION = "资产提取模型鉴权失败，请检查模型服务的 API Key。"


class AssetExtractionGatewayError(RuntimeError):
    error_code = GENERIC_CODE

    def __init__(self, usage: dict | None = None) -> None:
        super().__init__(GENERIC_MESSAGE)
        self.usage = usage or {}

    @classmethod
    def from_exception(cls, error):
        result = cls(getattr(error, "usage", None))
        if isinstance(error, ModelOutputLimitError):
            code, message = "output_length", OUTPUT_LIMIT
        elif isinstance(error, (ModelHTTPError, APIStatusError)):
            body = error.body if isinstance(error.body, dict) else {}
            detail = body.get("error", body)
            reason = str(detail.get("code") or detail.get("type") or "").lower() if isinstance(detail, dict) else ""
            if error.status_code == 401:
                code, message = "authentication_error", AUTHENTICATION
            elif error.status_code == 402 or reason in {"insufficient_quota", "insufficient_balance"}:
                code, message = "insufficient_quota", BALANCE
            else:
                return result
        else:
            return result
        result.error_code = code
        result.args = (localized_message(message),)
        return result


async def describe_extraction_failure(task):
    if task and task.task_type == AiTaskTypeEnum.extraction and task.error_message == GENERIC_MESSAGE:
        failure = await AgentOperation.get_or_none(task_id=task.id, key="recovery:failure", state="completed")
        if failure and any(issue.get("code") == "output_length" for issue in failure.result.get("issues", [])):
            task.error_message = localized_message(OUTPUT_LIMIT)
    return task
