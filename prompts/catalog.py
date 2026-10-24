"""Localized display/serialization labels, without creative instructions."""

from functools import lru_cache
import json
from pathlib import Path
from utils.prompt_language import normalize_prompt_language


def read_resource(root: Path, name: str, language: str) -> str:
    directory = root / normalize_prompt_language(language)
    path = directory / name
    if path.parent != directory:
        raise ValueError("Prompt names must be plain filenames")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def catalog(name: str, language: str = "zh") -> dict:
    return json.loads(read_resource(Path(__file__).with_name("locales"), name, language))
