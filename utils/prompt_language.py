from typing import Literal

PromptLanguage = Literal["zh", "en"]
DEFAULT_PROMPT_LANGUAGE: PromptLanguage = "en"


def normalize_prompt_language(value: str | None) -> PromptLanguage:
    """Normalize persisted/task values and keep old tasks backward compatible."""
    return "zh" if value == "zh" else DEFAULT_PROMPT_LANGUAGE


def prompt_language_name(value: str | None) -> str:
    return "简体中文" if normalize_prompt_language(value) == "zh" else "英文"
