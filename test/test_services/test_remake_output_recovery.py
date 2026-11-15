import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from schemas.agent_workflow import RemakeShot
from test.remake_fixtures import remake_shot
from services.remake.output_recovery import recover_shot_output


@pytest.mark.asyncio
async def test_recovers_only_when_creative_fields_are_complete(monkeypatch):
    raw = remake_shot()
    shot = RemakeShot.model_validate({k:v for k,v in raw.items() if k in RemakeShot.model_fields})
    data = shot.model_dump(mode="json")
    data.pop("confidence")
    refs = data.pop("asset_refs")
    text = json.dumps(data, ensure_ascii=False)[:-1] + ', "asset_refs": ' + json.dumps(refs, ensure_ascii=False)[:-1] + ', {'
    monkeypatch.setattr("services.remake.output_recovery.AgentMessage.get_or_none",
        AsyncMock(return_value=SimpleNamespace(native_messages=[{"parts":[{"part_kind":"text","content":text}]}])))
    recovered = await recover_shot_output(uuid4(), 71)
    assert recovered is not None and recovered.confidence is None
    assert recovered.actions == shot.actions and recovered.asset_refs == shot.asset_refs
    monkeypatch.setattr("services.remake.output_recovery.AgentMessage.get_or_none",
        AsyncMock(return_value=SimpleNamespace(native_messages=[{"parts":[{"part_kind":"text","content":'{"actions": ["cut'}]}])))
    assert await recover_shot_output(uuid4(), 71) is None
