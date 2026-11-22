import pytest

from test.remake_fixtures import synthetic_snapshot


def test_broken_inventory_keeps_named_assets_and_unmodified_model_reply():
    from services.remake.delivered_output import delivered_assets
    raw = '{"characters":[{"name":"男子","description":"坐在红椅上"},{"name":"海鸥","description":"灰翅","visual_fields":"物种"}],"scenes":"name"}'
    assets = delivered_assets(raw, synthetic_snapshot(), 'zh', '9:16')
    assert [row['name'] for row in assets['characters']] == ['男子','海鸥']
    assert '灰翅' in assets['characters'][1]['description']
    assert assets['objects'] == assets['scenes'] == []


def test_incomplete_shot_rows_are_saved_individually_without_a_model_repair():
    from services.remake.delivered_output import delivered_batch
    spans = [{'sequence':i,'start_seconds':(i-1)*4,'end_seconds':i*4,'output_seconds':4} for i in (1,2,3)]
    result = delivered_batch({'shots':[{'sequence':1,'prompt':'第一镜原文'}, {'sequence':3,'description':'第三镜原文'}]},spans)
    assert list(result) == [1,3]
    assert result[1]['source_prompt_text'] == '第一镜原文'
    assert '第三镜原文' in result[3]['source_prompt_text']


@pytest.mark.asyncio
@pytest.mark.parametrize('json_mode', [True, False])
async def test_model_reply_is_saved_once_without_a_repair_turn(monkeypatch, json_mode):
    from unittest.mock import AsyncMock
    from pydantic_ai.models.function import FunctionModel, DeltaToolCall
    from schemas.agent_workflow import RemakeTimedAssets
    from models.config import AiModelConfig
    from models.ai_task import AiTask
    from models.agent_operation import AgentOperation
    from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
    from services.creation_agent.production import conversation_for_task
    from test.test_services.test_skill_workflow import enabled_project

    novel, _, _ = await enabled_project()
    workflow = await prepare_workflow({'novel_id':novel.id,'prompt_language':'zh'})
    await AiModelConfig.filter(id=workflow['assistant_model_config_id']).update(supports_json_output=json_mode)
    task = await AiTask.create(task_type=6,status=2,request_params=workflow)
    msg = await conversation_for_task(task)
    calls = []
    async def respond(messages, info):
        calls.append(info)
        raw = '{"characters":[{"name":"海鸥","description":"展开翅膀","visual_fields":"物种"}],"scenes":"name"}'
        if json_mode:
            yield raw
        else:
            yield {0:DeltaToolCall(name=info.output_tools[0].name,json_args=raw,tool_call_id='inventory')}
    model = FunctionModel(stream_function=respond)
    model.client = AsyncMock()
    monkeypatch.setattr('services.creation_agent.handler.configured_model',lambda *a,**kw:model)
    execution = SkillExecution({**workflow,'remake_context_version':5,'remake_action_memory':'timeline',
                                'task_id':str(task.id)},msg,AsyncMock())
    result = await execution.generate('remake',{'output_kind':'global_key_assets','segment':1},RemakeTimedAssets)
    assert [v['name'] for v in result['characters']] == ['海鸥'] and len(calls)==1
    assert (await AgentOperation.get(task=task,key='model:remake:RemakeTimedAssets:1')).result == result

def test_plain_text_reaches_the_saved_prompt_even_without_structured_fields():
    from services.remake.delivered_output import delivered_shot
    from services.remake.handoff import finalize_generation_shots
    from services.remake.storyboards import prepare_remake_prompt
    prompt = '海滩上，女人举着甜筒。'
    shot = delivered_shot(prompt)
    material, = finalize_generation_shots([{**shot, 'shot_index':1, 'source_interval':{
        'start_seconds':0, 'end_seconds':4.2, 'output_seconds':4}}], 'zh')
    result = prepare_remake_prompt(material, [], synthetic_snapshot(), 'zh')
    assert result['prompt'] == prompt and result['duration_seconds'] == 4
