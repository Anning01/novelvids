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


def localized_message(source: str, *, _language: str | None = None, **parameters: object) -> str:
    language = _language or task_language.get() or message_language.get()
    template = CATALOG.get(source, source) if language == "en" else source
    return re.sub(r"\{(p\d+)\}", lambda match: str(parameters[match[1]]), template)


def public_generation_error(value: str | None) -> str | None:
    """Present known generation failures without exposing internal details."""
    if value and re.match(r'^\d+ validation errors? for Story(?:Candidate|Review|Evidence)(?:\r?\n|$)', value):
        return localized_message('模型返回的故事记忆格式不符合要求，结果未入库。请重试当前操作或更换模型。')
    if value and ('核对' in value or re.search(r'\b(?:needs?|pending|awaiting|manual) review\b', value, re.I)):
        return localized_message('生成未完成，可以重新生成。已完成结果会保留。')
    return value
