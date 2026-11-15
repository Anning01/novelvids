"""Recover complete creative fields when only trailing reference metadata was cut off."""
from uuid import UUID, uuid5

from pydantic import ValidationError
from pydantic_core import from_json

from models.creation_agent import AgentMessage
from schemas.agent_workflow import RemakeShot


async def recover_shot_output(task_id, index):
    child_id = uuid5(UUID(str(task_id)), f"model:remake:RemakeShot:{index}")
    message = await AgentMessage.get_or_none(task_id=child_id, role="assistant")
    if message is None:
        return None
    texts = [part["content"] for entry in message.native_messages or []
             for part in entry.get("parts", []) if part.get("part_kind") == "text"]
    if not texts:
        return None
    try:
        data = from_json(texts[-1], allow_partial=True)
        if not isinstance(data, dict):
            return None
        if not set(RemakeShot.model_fields).difference({"confidence"}).issubset(data):
            return None
        if next(reversed(data), None) not in {"asset_refs", "confidence"}:
            return None
        references = data.get("asset_refs")
        if isinstance(references, list) and references and references[-1] == {}:
            data["asset_refs"] = references[:-1]
        # A confidence score is optional metadata. All creative fields must still parse.
        return RemakeShot.model_validate(data)
    except (ValueError, ValidationError):
        return None
