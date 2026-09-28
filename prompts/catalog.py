"""Read-only, language-specific prompt resources. Missing translations fail explicitly."""

from functools import lru_cache
import json
from pathlib import Path
from utils.prompt_language import normalize_prompt_language

_ROOT = Path(__file__).with_name("templates")


@lru_cache(maxsize=None)
def template(name: str, language: str = "zh") -> str:
    path = _ROOT / normalize_prompt_language(language) / name
    if path.parent != _ROOT / normalize_prompt_language(language):
        raise ValueError("Prompt names must be plain filenames")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def catalog(name: str, language: str = "zh") -> dict:
    return json.loads(template(name, language))


def text(key: str, language: str = "zh", **values: object) -> str:
    return catalog("messages.json", language)[key].format(**values)
