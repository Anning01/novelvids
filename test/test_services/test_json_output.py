from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from services.llm.json_output import (
    JsonCompletionError,
    JsonCompletionTruncatedError,
    completion_usage,
    create_json_completion,
)


class ExamAnswer(BaseModel):
    question: str
    answer: str


def fake_client(content: str, finish_reason: str = "stop"):
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, refusal=None),
            finish_reason=finish_reason,
        )]
    ))
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    ), create


@pytest.mark.asyncio
async def test_supported_model_uses_json_object_response_format():
    client, create = fake_client('{"question":"Q","answer":"A"}')

    result, _ = await create_json_completion(
        client,
        model="structured-model",
        messages=[{"role": "user", "content": "Q A"}],
        response_model=ExamAnswer,
        supports_json_output=True,
    )

    assert result == ExamAnswer(question="Q", answer="A")
    assert create.await_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_unsupported_model_uses_prompt_and_parses_fenced_json():
    client, create = fake_client(
        '这里是结果：\n```json\n{"question":"Q","answer":"A"}\n```'
    )

    result, _ = await create_json_completion(
        client,
        model="prompt-only-model",
        messages=[{"role": "user", "content": "Q A"}],
        response_model=ExamAnswer,
        supports_json_output=False,
    )

    assert result.answer == "A"
    request = create.await_args.kwargs
    assert "response_format" not in request
    assert request["messages"][0]["role"] == "system"
    assert "JSON Schema" in request["messages"][0]["content"]


@pytest.mark.asyncio
async def test_truncated_completion_raises_a_precise_retryable_error():
    client, _create = fake_client('{"question":"Q"', finish_reason="length")

    with pytest.raises(JsonCompletionTruncatedError):
        await create_json_completion(
            client,
            model="prompt-only-model",
            messages=[{"role": "user", "content": "Q A"}],
            response_model=ExamAnswer,
        )


def test_completion_usage_reads_openai_usage():
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46)
    )
    assert completion_usage(completion) == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }


def test_completion_usage_missing_usage_is_empty():
    assert completion_usage(SimpleNamespace()) == {}


@pytest.mark.asyncio
async def test_parse_failure_carries_usage():
    client, _ = fake_client("not json at all", finish_reason="stop")
    original = client.chat.completions.create.return_value
    original.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    with pytest.raises(JsonCompletionError) as captured:
        await create_json_completion(
            client,
            model="m",
            messages=[{"role": "user", "content": "x"}],
            response_model=ExamAnswer,
        )
    assert captured.value.usage["prompt_tokens"] == 10
