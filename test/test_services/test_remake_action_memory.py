"""Continuity at camera edits, independent of the language used to describe a movement."""
import pytest
from services.remake.handoff import finalize_generation_shots
from test.remake_fixtures import remake_shot


def view(start, end, onset, movement, continuation, *, key="woman/offering/cone", restart=None):
    return dict(start=start, end=end, onset=onset, key=key, movement=movement,
                continuation=continuation, restart=restart)


def shot(index, start, end, actions):
    return {**remake_shot(index, refs=[]), "actions": actions, "shot_index": index, "sound_design": {"ambience":"Wind", "cues":[]},
            "source_interval": {"start_seconds": start, "end_seconds": end, "output_seconds": round(end-start)}}


def test_camera_reverse_angle_does_not_restart_motion_and_real_repeat_survives():
    a = view(19, 21.6, 19, "女子把甜筒送到他嘴前。", "甜筒在男子嘴前。")
    b = view(21.8, 23.3, 21.8, "女子笑着把甜筒递向男子。", "过肩镜头，女子保持伸手，广告语出现。")
    c = view(23.4, 24.6, 23.4, "女子第二次递出。", "甜筒已在手边。", restart={"at":23.35, "seen":"男子推回甜筒，女子把手收回到桌边。"})
    s = shot(2, 12.933333, 24.733333, [a,b,c])
    s["sound_design"] = {"ambience":"海风持续", "cues":[{"start":14, "end":15, "sound":"下坠呼啸"}]}
    result, = finalize_generation_shots([s], "zh")
    assert "送到他嘴前" in result["actions"][0]
    assert result["actions"][1].endswith(b["continuation"])
    assert result["unconfirmed_restarts"] == [{"key":b["key"], "source_seconds":21.8}]
    assert result["actions"][2].endswith(c["movement"])
    assert "1.085s-2.102s" in result["sound_design"]


def test_motion_across_generated_shots_and_independent_simultaneous_actions():
    a = view(1,4,1,"He lifts the box.","The box rises.",key="he/lift/box")
    b = view(4,6,1,"He hoists it.","Reverse angle: the raised box clears the shelf.",key="he/lift/box")
    c = view(4,6,4,"She opens the door.","The door is open.",key="she/open/door")
    previous,current = finalize_generation_shots([shot(1,0,4,[a]),shot(2,4,8,[b,c])],"en")
    assert previous["actions"][0].endswith(a["movement"])
    assert current["actions"][0].endswith(b["continuation"])
    assert current["actions"][1].endswith(c["movement"])
    assert "handoff" not in current


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.asyncio
async def test_motion_wire_recovery_and_final_prompt_use_one_request(tmp_path, batch, language):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from prompts.remake import motion_memory_instruction
    from schemas.remake_motion import shot_contracts
    from services.creation_agent.skill_execution import current_execution
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from services.remake.output_recovery import recover_short_rows, recover_shot_text
    from services.remake.storyboards import prepare_remake_prompt
    from test.remake_fixtures import synthetic_snapshot
    from test.test_services.test_remake_gateway import _config, _Client
    from test.test_services.test_remake_short_storyboard import sample

    params = {"remake_context_version": 5, "remake_shot_limit": 15, "remake_action_memory": True}
    single, short = shot_contracts(params)
    base = sample(1)
    span = {"sequence": 1, "start_seconds": 12, "end_seconds": 24, "output_seconds": 12}
    observed = [view(16, 18, 16, "She reaches out.", "Her arm is extended."),
                view(18, 20, 16, "She offers it.", "Reverse angle: her arm stays extended.")]
    fields = dict(actions=observed, sound_design={"ambience":"Wind", "cues":[
        {"start":14, "end":15, "sound":"Impact"}, {"start":2,"end":3,"sound":"Outside"}]},
        last_visible_state="The box rests on the ledge.", asset_refs=[])
    wire = base["shots"][0] if batch else {k:v for k,v in remake_shot().items() if k in single.model_fields}
    wire.pop("transition")
    wire.update(fields)
    answer = short.model_validate(base) if batch else single.model_validate(wire)
    context = dict(assets=[], intervals=[span], storyboard_strategy="default", source_interval=span, duration_seconds=12)
    snap = synthetic_snapshot()

    async def respond(skill, facts, schema, **options):
        assert skill == "remake" and schema is (short if batch else single)
        assert motion_memory_instruction(language, batch=batch) == options["additional_instructions"]
        assert "onset" in options["additional_instructions"] and "last_visible_state" in options["additional_instructions"]
        assert "动作、运镜和切换按段内时间描述" not in options["additional_instructions"]
        await options["output_validator"](answer)
        return answer

    generate = AsyncMock(side_effect=respond)
    token = current_execution.set(SimpleNamespace(params=params, snapshot=snap, language=language, generate=generate))
    path = tmp_path/"source.mp4"
    path.write_bytes(b"sample")
    try:
        raw = await RemakeVideoAnalysisGateway(_config(), client=_Client([])).analyze_one(
            index=1, path=path, prompt="", context=context, schema_name="short_video_storyboard" if batch
            else "professional_video_prompt_material", response_schema={}, include_segment_metadata=False)
    finally:
        current_execution.reset(token)
    generate.assert_awaited_once()
    if batch:
        raw = short.model_validate(raw).materialize([span])[1]
        recovered = recover_short_rows(json.dumps(base)[:-2], [span], short)[1]
    else:
        recovered = recover_shot_text(answer.model_dump_json(by_alias=True), single).model_dump()
    assert recovered["actions"] == raw["actions"]
    material, = finalize_generation_shots([{**raw, "shot_index":1, "source_interval":span}], language)
    result = prepare_remake_prompt(material, [], snap, language)["prompt"]
    assert result.count("She reaches out.") == 1
    assert "She offers it." not in result and "her arm stays extended" in result
    assert "2s-3s: Impact" in result and "Outside" not in result


def test_stored_wire_keeps_old_jobs_readable_and_rejects_unusable_evidence():
    from pydantic import ValidationError
    from schemas.remake_motion import ActionView, shot_contracts
    from test.test_services.test_remake_short_storyboard import sample

    _, legacy = shot_contracts({})
    _, current = shot_contracts({"remake_action_memory": True})
    legacy.model_validate(sample(1))
    with pytest.raises(ValidationError):
        current.model_validate(sample(1))
    for field, value in (("onset", float("nan")), ("continuation", " ")):
        invalid = view(1, 3, 1, "Steps forward.", "Her foot is planted.")
        invalid[field] = value
        with pytest.raises(ValidationError):
            ActionView.model_validate(invalid)


def test_nested_camera_views_cannot_reintroduce_the_discarded_action():
    s = shot(1, 0, 4, [view(0,2,0,"She reaches.","Her hand remains out."),
                        view(2,4,0,"She reaches again.","Reverse angle: still holding the cup.")])
    segment = {"duration":2, "description":"Side view", "visual_prose":"Hand on cup",
               "shot_size_and_camera":"wide", "camera_movement":"static", "actions":["She reaches again."]}
    s["segments"] = [segment, dict(segment)]
    raw, = finalize_generation_shots([s], "en")
    assert [piece["actions"] for piece in raw["segments"]] == [[action] for action in raw["actions"]]
    from services.remake.storyboards import prepare_remake_prompt
    from test.remake_fixtures import synthetic_snapshot
    prompt = prepare_remake_prompt(raw, [], synthetic_snapshot(), "en")["prompt"]
    assert "She reaches again." not in prompt and prompt.count("Reverse angle: still holding the cup.") == 1


def test_paid_shots_can_be_read_when_restart_is_late_and_fields_are_inside_sound():
    from schemas.remake_motion import shot_contracts
    from test.test_services.test_remake_short_storyboard import sample
    _, batch = shot_contracts({"remake_action_memory": True})
    raw = sample(2)
    spans = []
    for i, row in enumerate(raw["shots"]):
        a = 4*i
        row["actions"] = [view(a, a+4, a, "Still in frame.", "New angle.",
                               restart={"at":a+1,"seen":"Object moves."})]
        row["sound_design"] = {"ambience":"Wind", "cues":[]}
        row["last_visible_state"] = row.pop("transition")
        if i == 1:
            for field in ("last_visible_state", "asset_refs", "dialogue", "narration"):
                row["sound_design"][field] = row.pop(field)
        spans.append({"sequence":i+1, "start_seconds":a, "end_seconds":a+4, "output_seconds":4})
    assert len(batch.model_validate(raw).materialize(spans)) == 2


@pytest.mark.parametrize("language", ["zh", "en"])
def test_new_timeline_keeps_model_wording_even_when_an_action_repeats(language):
    from prompts.remake import timeline_instruction
    from schemas.remake_motion import shot_contracts
    from services.remake.storyboards import prepare_remake_prompt
    from test.remake_fixtures import synthetic_snapshot
    from test.test_services.test_remake_short_storyboard import sample

    single, batch = shot_contracts({"remake_action_memory":"timeline"})
    wire = sample(1)
    row = wire["shots"][0]
    text = "镜头2 女子再次递出甜筒。"
    row.update(actions=[{"start":10,"end":12,"text":text},{"start":12,"end":14,"text":text}],
               sound_design={"ambience":"风声", "cues":[{"start":3,"end":2,"sound":"撞击声"}]}, asset_refs=[])
    span = {"start_seconds":10, "end_seconds":14, "output_seconds":4, "sequence":1}
    raw = batch.model_validate(wire).materialize([span])[1]
    s, = finalize_generation_shots([{**raw,"source_interval":span,"shot_index":1}],language)
    assert s["actions"] == [f"0s-2s: {text}", f"2s-4s: {text}"]
    assert s["sound_design"] == "风声 撞击声"
    assert text in prepare_remake_prompt(s,[],synthetic_snapshot(),language)["prompt"]
    assert single.model_fields['actions'].annotation != shot_contracts({"remake_action_memory":True})[0].model_fields['actions'].annotation
    assert "confirmed_handoff" in timeline_instruction(language,batch=False)
    assert "sound_design" in timeline_instruction(language,batch=True)


def test_split_asset_record_is_repacked_without_inventing_fields():
    from schemas.agent_workflow import RemakeTimedAssets
    from pydantic import ValidationError
    span = [{"start_seconds":1,"end_seconds":2}]
    row = {"name":"A","description":"description", "visual_fields":"地面':'细沙","海面":"蓝"}
    inventory = {"characters":[], "scenes":[row, "appearances", span, "name", "B", "description", "white",
                 "visual_fields", {"光":"亮"}, "appearances", span], "objects":[]}
    output = RemakeTimedAssets.model_validate(inventory)
    assert [s.name for s in output.scenes] == ["A","B"]
    assert output.scenes[0].visual_fields == {"地面":"细沙","海面":"蓝"}
    with pytest.raises(ValidationError):
        RemakeTimedAssets.model_validate({**inventory, "scenes":[row, "appearances"]})


@pytest.mark.asyncio
async def test_retry_recovers_finished_reply_locally_and_preserves_failed_call(monkeypatch):
    import json
    from unittest.mock import AsyncMock
    from models.ai_task import AiTask
    from models.agent_operation import AgentOperation
    from services.remake.checkpoints import reconcile_retry, completed_outputs
    from test.test_services.test_remake_short_storyboard import sample

    task = await AiTask.create(task_type=6, status=4,
        request_params={"remake_action_memory":"timeline","remake_context_version":5})
    key = "model:remake:RemakeShortStoryboard:1"
    await AgentOperation.create(task=task, key=key, state="failed", external=True)
    await AgentOperation.create(task=task, key="remake:short-input", state="completed",
        result={"intervals":[{"sequence":1,"start_seconds":0,"end_seconds":4,"output_seconds":4}]})
    raw = sample(1)
    raw["shots"][0].update(actions=[{"start":1,"end":2,"text":"杯子已举起。"}],
                           sound_design={"ambience":"风声"})
    monkeypatch.setattr("services.remake.output_recovery.latest_response_text",
                        AsyncMock(return_value=json.dumps(raw,ensure_ascii=False)))
    await reconcile_retry(task)
    await reconcile_retry(task)
    saved = await completed_outputs({**task.request_params,"retry_of_task_id":str(task.id)})
    assert saved["model:remake:RemakeShot:1"]["actions"] == raw["shots"][0]["actions"]
    assert (await AgentOperation.get(task=task,key=key)).state == "failed"
    assert await AgentOperation.filter(task=task,key="model:remake:RemakeShot:1").count() == 1
