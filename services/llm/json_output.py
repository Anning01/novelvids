"""兼容不同 OpenAI-compatible 服务的 JSON 输出调用。"""

import json
import re
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel


class JsonCompletionTruncatedError(ValueError):
    """The provider stopped before returning a complete structured response."""

    def __init__(self, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage = usage or {}


class JsonCompletionError(ValueError):
    """Structured JSON completion failed; carries token usage for billing."""

    def __init__(self, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage = usage or {}


def completion_usage(completion: Any) -> dict[str, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _extract_json(content: str) -> Any:
    """从纯 JSON、Markdown 代码块或带说明的文本中提取首个 JSON 值。"""
    text = (content or "").strip()
    if not text:
        raise ValueError("LLM 未返回内容")

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("LLM 返回内容中没有可解析的 JSON")


def _json_instruction(response_model: type[BaseModel]) -> str:
    schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    return (
        "请只返回一个合法的 JSON 对象，不要输出 Markdown 代码块、解释、思考过程或其他文字。"
        "JSON 必须严格符合以下 JSON Schema：\n"
        f"{schema}"
    )


async def create_json_completion(
    client: AsyncOpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    response_model: type[BaseModel],
    supports_json_output: bool = False,
    timeout: float | None = None,
) -> tuple[BaseModel, Any]:
    """调用模型并返回经 Pydantic 校验的对象及原始 completion。

    支持结构化输出的模型使用 ``json_object``；其他模型仅通过提示词约束，
    不发送可能被兼容服务拒绝的 ``response_format`` 参数。
    """
    controlled_messages = [dict(message) for message in messages]
    instruction = _json_instruction(response_model)
    system_index = next(
        (index for index, message in enumerate(controlled_messages) if message["role"] == "system"),
        None,
    )
    if system_index is None:
        controlled_messages.insert(0, {"role": "system", "content": instruction})
    else:
        controlled_messages[system_index]["content"] = (
            f"{controlled_messages[system_index]['content']}\n\n{instruction}"
        )

    request: dict[str, Any] = {
        "model": model,
        "messages": controlled_messages,
    }
    if supports_json_output:
        request["response_format"] = {"type": "json_object"}
    if timeout is not None:
        request["timeout"] = timeout

    completion = await client.chat.completions.create(**request)
    usage = completion_usage(completion)
    message = completion.choices[0].message
    finish_reason = getattr(completion.choices[0], "finish_reason", None)
    if finish_reason == "length":
        raise JsonCompletionTruncatedError(
            "模型输出达到 token 上限，结构化 JSON 未完成", usage=usage
        )
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise JsonCompletionError(f"模型拒绝生成 JSON：{refusal}", usage=usage)

    try:
        payload = _extract_json(message.content or "")
    except ValueError as exc:
        raise JsonCompletionError(str(exc), usage=usage) from None
    return response_model.model_validate(payload), completion
