"""Side-effect-free output language contract."""

from prompts.legacy.catalog import text


def output_language_rule(language: str) -> str:
    return text("language_rule", language)
