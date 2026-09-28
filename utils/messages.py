"""Local messages with explicit interpolation; external/provider text is untouched."""

import json
import re
from contextvars import ContextVar
from pathlib import Path
from utils.prompt_language import task_language

message_language: ContextVar[str] = ContextVar("message_language", default="zh")
CATALOG = json.loads(
    Path(__file__).with_name("messages.json").read_text(encoding="utf-8")
)


def localized_message(source: str, **parameters: object) -> str:
    language = task_language.get() or message_language.get()
    template = CATALOG.get(source, source) if language == "en" else source
    return re.sub(r"\{(p\d+)\}", lambda match: str(parameters[match[1]]), template)
