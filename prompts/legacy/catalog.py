"""Frozen bilingual resources for historical tasks; new creation uses skills."""

from functools import lru_cache
import json
from pathlib import Path
from prompts.catalog import read_resource

_ROOT = Path(__file__).with_name("templates")


@lru_cache(maxsize=None)
def template(name: str, language: str = "zh") -> str:
    return read_resource(_ROOT, name, language)


@lru_cache(maxsize=None)
def catalog(name: str, language: str = "zh") -> dict:
    return json.loads(template(name, language))


def text(key: str, language: str = "zh", **values: object) -> str:
    return catalog("messages.json", language)[key].format(**values)
