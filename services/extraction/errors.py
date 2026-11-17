"""Safe, user-facing reasons for failed extraction requests."""

from models.agent_operation import AgentOperation
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message

GENERIC_CODE = "asset_extraction_gateway_error"
GENERIC_MESSAGE = f"资产提取模型调用失败（错误代码：{GENERIC_CODE}）"
OUTPUT_LIMIT = "模型单次输出达到上限，资产提取未完成。请缩短本章内容，或选择支持更长输出的模型后重试。"


async def describe_extraction_failure(task):
    if task and task.task_type == AiTaskTypeEnum.extraction and task.error_message == GENERIC_MESSAGE:
        failure = await AgentOperation.get_or_none(task_id=task.id, key="recovery:failure", state="completed")
        if failure and any(issue.get("code") == "output_length" for issue in failure.result.get("issues", [])):
            task.error_message = localized_message(OUTPUT_LIMIT)
    return task
