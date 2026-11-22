"""Recover complete creative fields when only trailing reference metadata was cut off."""
import json
from uuid import UUID, uuid5

from pydantic import ValidationError
from pydantic_core import from_json

from models.creation_agent import AgentMessage
from models.agent_operation import AgentOperation
from schemas.agent_workflow import RemakeShot


async def recover_shot_output(task_id, index, schema=RemakeShot):
    text = await latest_response_text(task_id, f"model:remake:RemakeShot:{index}")
    return recover_shot_text(text, schema) if text else None


async def latest_response_text(task_id, key):
    child_id = uuid5(UUID(str(task_id)), key)
    message = await AgentMessage.get_or_none(task_id=child_id, role="assistant")
    if message is None:
        return None
    # An interrupted stream can have a durable response even when the conversation history
    # still ends at the request. Use its latest answer, never a superseded repair candidate.
    receipt = await AgentOperation.filter(task_id=child_id, key__startswith="model-response:", state="completed").order_by("-id").first()
    history = receipt.result.get("messages", []) if receipt else (message.native_messages or [])
    texts = [part["content"] for entry in history
             for part in entry.get("parts", []) if part.get("part_kind") == "text"]
    if not texts:
        return None
    return texts[-1]


def _complete_body_before_segments(text, schema):
    # Decode whole top-level values. A partial parser can otherwise promote a cut-off
    # string or nested object to an apparently valid creative field.
    decoder = json.JSONDecoder()
    text = text.strip()
    if not text.startswith("{"):
        return None
    pos = 1
    body = {}
    while pos < len(text):
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        key, pos = decoder.raw_decode(text, pos)
        if not isinstance(key, str) or key in body:
            return None
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if text[pos:pos+1] != ":":
            return None
        pos += 1
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if key == "segments" and text[pos:pos+1] == "[":
            try:
                decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                # Reject malformed JSON in the middle, rather than treating it as an interrupted stream.
                from_json(text, allow_partial=True)
                if {"dialogue", "narration"}.issubset(body):
                    return schema.model_validate(body)
            return None
        body[key], pos = decoder.raw_decode(text, pos)
        pos += len(text[pos:]) - len(text[pos:].lstrip())
        if text[pos:pos+1] != ",":
            return None
        pos += 1
    return None


def recover_shot_text(text, schema=RemakeShot):
    try:
        return schema.model_validate_json(text)
    except ValidationError:
        pass
    try:
        recovered = _complete_body_before_segments(text, schema)
        if recovered is not None:
            return recovered
    except (ValueError, ValidationError):
        pass
    try:
        data = from_json(text, allow_partial=True)
        if not isinstance(data, dict):
            return None
        present = {name for name, field in schema.model_fields.items() if name in data or field.alias in data}
        if not set(schema.model_fields).difference({"confidence"}).issubset(present):
            return None
        if next(reversed(data), None) not in {"asset_refs", "confidence"}:
            return None
        references = data.get("asset_refs")
        if isinstance(references, list) and references and references[-1] == {}:
            data["asset_refs"] = references[:-1]
        # A confidence score is optional metadata. All creative fields must still parse.
        return schema.model_validate(data)
    except (ValueError, ValidationError):
        return None


def recover_short_rows(text, intervals, schema=None):
    """Keep only fully delimited shot objects already delivered by the provider."""
    from schemas.remake_short import RemakeShortStoryboard
    schema = schema or RemakeShortStoryboard
    if not text:
        return {}
    spans = {span["sequence"]: span for span in intervals}
    decoder = json.JSONDecoder()
    text = text.strip()
    if not text.startswith("{"):
        return {}
    pos = 1
    result = {}
    try:
        # looks precedes shots in the wire schema. Never guess missing shared styles.
        looks = None
        while pos < len(text):
            pos += len(text[pos:]) - len(text[pos:].lstrip())
            key, pos = decoder.raw_decode(text, pos)
            tail = text[pos:].lstrip()
            if not tail.startswith(":"):
                return {}
            pos = len(text) - len(tail[1:].lstrip())
            if key == "shots" and looks is not None and text[pos:pos+1] == "[":
                pos += 1
                while pos < len(text):
                    pos += len(text[pos:]) - len(text[pos:].lstrip())
                    if text[pos:pos+1] == "]":
                        break
                    row, pos = decoder.raw_decode(text, pos)
                    one = schema.model_validate({"looks": looks, "shots": [row]})
                    index = one.shots[0].sequence
                    if index not in spans or index in result:
                        return {}
                    result.update(one.materialize([spans[index]]))
                    tail = text[pos:].lstrip()
                    if not tail.startswith(","):
                        break
                    pos = len(text) - len(tail) + 1
                return result
            if key != "looks" or looks is not None:
                return {}
            looks, pos = decoder.raw_decode(text, pos)
            tail = text[pos:].lstrip()
            if not tail.startswith(","):
                return {}
            pos = len(text) - len(tail) + 1
    except json.JSONDecodeError:
        return result
    except (ValueError, TypeError):
        return {}
    return result
