"""Side-effect-free output language contract."""

from prompts.catalog import text


def output_language_rule(language: str) -> str:
    return text("language_rule", language)
