"""Storyboard model orchestration with bounded continuation batches."""

import json
from typing import Any

from openai import AsyncOpenAI

from prompts.storyboard import build_storyboard_messages
from schemas.scene import SceneEntity, Storyboard
from services.llm.json_output import (
    JsonCompletionTruncatedError,
    create_json_completion,
)
from services.storyboard.chunking import NarrativeChunker
from services.storyboard.strategies import storyboard_strategy_factory


def _message_characters(messages: list[dict[str, str]]) -> int:
    schema_characters = len(
        json.dumps(Storyboard.model_json_schema(), ensure_ascii=False)
    )
    return sum(len(message["content"]) for message in messages) + schema_characters


def _usage_values(completion: Any) -> dict[str, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _aggregate_metadata(completions: list[Any]) -> dict[str, Any]:
    last_completion = completions[-1]
    usage_totals: dict[str, int] = {}
    response_ids: list[str] = []
    refusal: str | None = None
    for completion in completions:
        response_id = getattr(completion, "id", None)
        if response_id:
            response_ids.append(response_id)
        for key, value in _usage_values(completion).items():
            usage_totals[key] = usage_totals.get(key, 0) + value
        choices = getattr(completion, "choices", [])
        if choices:
            refusal = getattr(choices[0].message, "refusal", None) or refusal

    metadata: dict[str, Any] = {
        "model": getattr(last_completion, "model", None),
        "response_id": getattr(last_completion, "id", None),
        "response_ids": response_ids,
        "created": getattr(last_completion, "created", None),
        "system_fingerprint": getattr(last_completion, "system_fingerprint", None),
        "batch_count": len(completions),
    }
    if usage_totals:
        metadata["usage"] = usage_totals
    if refusal:
        metadata["refusal"] = refusal
    return metadata


async def generate_storyboard(
    client: AsyncOpenAI,
    long_text: str,
    entities: list[SceneEntity],
    model: str,
    supports_json_output: bool = False,
    prompt_language: str = "zh",
    max_context_characters: int | None = None,
    thinking: str | None = None,
    max_tokens: int | None = None,
    storyboard_strategy: str | None = None,
) -> tuple[Storyboard, dict[str, Any]]:
    """Generate fresh bounded calls and carry only a continuity summary."""
    strategy = storyboard_strategy_factory.resolve(storyboard_strategy)
    fixed_messages = build_storyboard_messages(
        "",
        entities,
        prompt_language,
        strategy=strategy,
    )
    chunker = NarrativeChunker.for_context_limit(
        max_context_characters,
        _message_characters(fixed_messages),
    )
    chunks = chunker.split(long_text)
    shots = []
    completions: list[Any] = []
    batch_index = 0

    while batch_index < len(chunks):
        previous_shot = shots[-1] if shots else None
        messages = build_storyboard_messages(
            chunks[batch_index],
            entities,
            prompt_language,
            batch_index=batch_index,
            batch_count=len(chunks),
            next_sequence=len(shots) + 1,
            previous_shot=previous_shot,
            strategy=strategy,
        )
        try:
            batch_storyboard, completion = await create_json_completion(
                client,
                model=model,
                messages=messages,
                response_model=Storyboard,
                supports_json_output=supports_json_output,
                timeout=600,
                thinking=thinking,
                max_tokens=max_tokens,
            )
        except JsonCompletionTruncatedError:
            retry_chunks = chunker.split_for_retry(chunks[batch_index])
            if len(retry_chunks) <= 1:
                raise
            chunks[batch_index : batch_index + 1] = retry_chunks
            continue

        for shot in batch_storyboard.shots:
            shots.append(shot.model_copy(update={"sequence": len(shots) + 1}))
        completions.append(completion)
        batch_index += 1

    if not completions:
        raise ValueError("分镜模型未返回任何批次结果")
    return Storyboard(shots=shots), _aggregate_metadata(completions)
