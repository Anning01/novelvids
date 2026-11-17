"""Identify historical inventory receipts without executing the retired reader."""
import hashlib
import json


def cast_segment(chapter: dict, language: str, revision: str) -> str:
    source = json.dumps([chapter, language, revision], ensure_ascii=False, sort_keys=True)
    return f"chapter-cast:v2:{chapter['id']}:{hashlib.sha256(source.encode()).hexdigest()}"
