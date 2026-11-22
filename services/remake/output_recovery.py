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


async def recover_failed_material(task):
    """Re-read complete model replies after a format failure, without submitting or changing the external call."""
    from models.novel import Novel
    from prompts.skill_pack import SkillSnapshot
    from schemas.agent_workflow import remake_asset_schema
    from schemas.remake_motion import shot_contracts
    from services.remake.asset_validation import render_remake_assets

    params = task.request_params
    asset_type = remake_asset_schema(params)
    shot_type, batch_type = shot_contracts(params)
    failed = await AgentOperation.filter(task=task, external=True, state="failed", key__startswith="model:remake:")
    for receipt in failed:
        kind = receipt.key.split(":")[2]
        if kind not in (asset_type.__name__, batch_type.__name__, shot_type.__name__):
            continue
        text = await latest_response_text(task.id, receipt.key)
        if not text:
            continue
        try:
            if kind == asset_type.__name__:
                project = await Novel.get(id=params["novel_id"])
                snapshot = SkillSnapshot.model_validate(params["skill_snapshot"])
                if params.get("remake_action_memory") == "timeline":
                    from services.remake.delivered_output import delivered_assets
                    assets = delivered_assets(text, snapshot, params["prompt_language"], project.aspect_ratio or "16:9")
                else:
                    assets = render_remake_assets(asset_type.model_validate_json(text).model_dump(), snapshot,
                        params["prompt_language"], project.aspect_ratio or "16:9")
                values = {"remake:recovered-assets": assets}
            elif kind == batch_type.__name__:
                manifest = await AgentOperation.get_or_none(task=task, key="remake:short-input", state="completed")
                if not manifest:
                    continue
                if params.get("remake_action_memory") == "timeline":
                    from services.remake.delivered_output import delivered_batch
                    rows = delivered_batch(text, manifest.result["intervals"])
                else:
                    rows = batch_type.model_validate_json(text).materialize(manifest.result["intervals"])
                values = {f"model:remake:RemakeShot:{i}": row for i, row in rows.items()}
            else:
                index = receipt.key.rsplit(":", 1)[1]
                if not index.isdigit():
                    continue
                if params.get("remake_action_memory") == "timeline":
                    from services.remake.delivered_output import delivered_shot
                    shot = delivered_shot(text)
                else:
                    shot = shot_type.model_validate_json(text).model_dump(mode="json")
                values = {f"remake:recovered-shot:{index}": shot}
        except ValueError:
            continue
        for key, value in values.items():
            await AgentOperation.get_or_create(task=task, key=key, defaults={"state":"completed", "result":value})
