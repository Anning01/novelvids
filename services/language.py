"""Application language loading and immutable per-task language scope."""

from models.config import GeneralConfig
from utils.prompt_language import (
    DEFAULT_PROMPT_LANGUAGE,
    normalize_prompt_language,
    task_language,
)

# None means no task scope (e.g. an interactive preview).


async def configured_language() -> str:
    config = await GeneralConfig.get_or_none(id=1)
    return normalize_prompt_language(
        config.prompt_language if config else DEFAULT_PROMPT_LANGUAGE
    )


async def generation_language() -> str:
    return task_language.get() or await configured_language()
