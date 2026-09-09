"""Agent persistence → existing media controllers → captured provider HTTP bodies."""

import json
import re
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart, RetryPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from controllers.video import video_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.scene import Scene
from schemas.video import VideoGenerateRequest
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from services.creation_agent.tools import PromptEditService
from services.reference.handler import AssetReferenceHandler
from test.creation_agent_evaluation import create_evaluation_project, load_cases
from test.test_services.test_video_generation_capabilities import _video_config
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def agent_edit(novel_id, targets, tool_name, edits_for):
    task = await AiTask.create(task_type=AiTaskTypeEnum.creation_agent.value, status=TaskStatusEnum.running.value, request_params={"novel_id": novel_id})
    service = PromptEditService(novel_id=novel_id, task_id=task.id, allowed_targets=set(targets), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read')])
        if calls == 2:
            context = next(part.content for message in messages for part in message.parts if isinstance(part, ToolReturnPart))
            return ModelResponse(parts=[ToolCallPart(tool_name, {'edits': edits_for(context['targets'])}, tool_call_id='write')])
        result = [part.content for message in messages for part in message.parts if isinstance(part, ToolReturnPart)][-1]
        assert result.get('status') == 'saved', [part.content for message in messages for part in message.parts if isinstance(part, RetryPromptPart)]
        return ModelResponse(parts=[TextPart('已保存当前授权对象。')])

    await creation_agent.run('仅修改已选择的提示词。', model=FunctionModel(model), deps=CreationAgentDeps(service=service, context={}),
                             usage_limits=UsageLimits(request_limit=3))


def capture_http(monkeypatch, bodies, response):
    client = httpx.AsyncClient
    def transport(request):
        assert request.method == 'POST'
        assert request.url.path.endswith(('/contents/generations/tasks', '/images/generations'))
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response)
    def factory(*args, **kwargs):
        kwargs['transport'] = httpx.MockTransport(transport)
        return client(*args, **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', factory)


@pytest.mark.asyncio
@pytest.mark.parametrize('with_images', [False, True])
async def test_a_b_and_later_chapter_remain_independent_in_actual_video_http_payloads(monkeypatch, with_images):
    novel, _, targets = await create_evaluation_project(next(case for case in load_cases() if case.id == 'S01'))
    selected = [targets[label] for label in ('A', 'B', 'I')]
    labels = {id: label for label, (_, id) in targets.items() if label in ('A', 'B', 'I')}
    for asset in await Asset.filter(novel=novel):
        asset.main_image = f'https://cdn.example.invalid/{asset.id}.png' if with_images else None
        await asset.save()
    variant = await AssetVariant.get(asset__novel=novel)
    variant.images = ['https://cdn.example.invalid/raincoat.png'] if with_images else []
    await variant.save()

    def edits(current):
        return [{'scene_id': item['id'], 'changes': {'segments': [
            {'duration': 2, 'description': f"{labels[item['id']]}独有动作{index}", 'shot_size_and_camera': '中景',
             'visual_prose': f"@{{林岚}}在@{{站台}}握紧雨伞，{labels[item['id']]}独有细节{index}。",
             'actions': ['@{林岚}抬头看向站台灯。'], 'camera_movement': '固定机位'} for index in (1, 2, 3)]}}
            for item in current]
    await agent_edit(novel.id, selected, 'update_storyboard_prompt', edits)
    assert await Scene.filter(chapter__novel=novel).count() == 12
    config = await _video_config('seedance_2_5')
    bodies = []
    capture_http(monkeypatch, bodies, {'id': 'synthetic-video-task'})
    for _, id in selected:
        await video_controller.generate(VideoGenerateRequest(scene_id=id, model_config_id=config.id, duration=6))
    assert len(bodies) == 3
    for label, body in zip(('A', 'B', 'I'), bodies):
        prompt = next(item['text'] for item in body['content'] if item['type'] == 'text')
        assert re.findall(r'【镜头(\d+)\s*·', prompt) == ['1', '2', '3']
        assert body['duration'] == 6
        assert f'{label}独有细节' in prompt
        assert all(f'{other}独有细节' not in prompt for other in ('A', 'B', 'I') if other != label)
        assert '黑色齐肩短发' in prompt
        if label == 'I':
            assert '蓝色长雨衣' in prompt and '左手缠白色绷带' in prompt
        else:
            assert '灰色粗纺风衣' in prompt
            assert '白色绷带' not in prompt and '蓝色长雨衣' not in prompt
        assert '镜头1的女生' not in prompt and '服装同上' not in prompt
        references = [item['image_url']['url'] for item in body['content'] if item['type'] == 'image_url']
        assert bool(references) is with_images
        if with_images:
            assert ('https://cdn.example.invalid/raincoat.png' in references) is (label == 'I')
    assert [(await Scene.get(id=id)).sequence for _, id in selected] == [1, 2, 1]


@pytest.mark.asyncio
async def test_saved_base_and_variant_image_prompts_reach_the_image_http_request(monkeypatch):
    novel, _, targets = await create_evaluation_project(load_cases()[0])
    selected = [targets['heroine'], targets['raincoat']]
    desired = {'asset': '黑色齐肩短发，灰色风衣，柔和窗光，独立主形象。',
               'variant': '黑色齐肩短发，蓝色雨衣，雨滴纹理，独立雨衣形态。'}
    await agent_edit(novel.id, selected, 'update_image_prompt', lambda current: [
        {'target_kind': item['kind'], 'target_id': item['id'], 'prompt': desired[item['kind']]}
        for item in current])
    bodies = []
    capture_http(monkeypatch, bodies, {'data': [{'url': 'https://cdn.example.invalid/output.png'}]})
    monkeypatch.setattr('services.reference.handler._download_image', AsyncMock(return_value='/media/synthetic-output.png'))
    base = {'asset_id': targets['heroine'][1], 'base_url': 'https://images.example.invalid/v1',
            'api_key': 'synthetic-key', 'model': 'test-image-model'}
    await AssetReferenceHandler().execute(base)
    await AssetReferenceHandler().execute({**base, 'variant_id': targets['raincoat'][1]})
    assert [body['prompt'] for body in bodies] == [desired['asset'], desired['variant']]
    variant = await AssetVariant.get(id=targets['raincoat'][1])
    assert variant.chapter_numbers == [3]
