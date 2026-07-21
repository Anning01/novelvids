from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from services.llm.json_output import create_json_completion


class ExamAnswer(BaseModel):
    question: str
    answer: str


def fake_client(content: str):
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=None))]
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
