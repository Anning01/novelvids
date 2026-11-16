"""Exercise real SSE decoding through generation, validation and storyboard persistence."""
import json
from unittest.mock import patch

import httpx
import pytest
from openai import AsyncOpenAI

from controllers.scene import scene_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.config import GeneralConfig
from models.scene import Scene
from services.ai_task_executor import ai_task_executor
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_storyboard_partial_repair import raw_shot


class StreamBody(httpx.AsyncByteStream):
    def __init__(self, events, interrupted):
        self.events, self.interrupted = events, interrupted

    async def __aiter__(self):
        for event in self.events:
            yield ('data: ' + json.dumps(event) + '\n\n').encode()
        if self.interrupted:
            raise httpx.RemoteProtocolError('peer closed connection without sending complete message body (incomplete chunked read)')
        yield b'data: [DONE]\n\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupted', [False, True])
@pytest.mark.parametrize('replace_existing', [False, True])
async def test_complete_storyboard_survives_transport_close_after_finish(interrupted, replace_existing):
    novel, chapter, _ = await enabled_project()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': 'zh'})
    asset = await Asset.create(novel=novel, canonical_name='Alex', asset_type=1, base_traits='灰衣少年', source_chapters=[1])
    variant = await AssetVariant.create(asset=asset, name='战斗', base_traits='黑甲', chapter_numbers=[1])
    if replace_existing:
        await Scene.create(chapter=chapter, sequence=1, prompt='旧分镜', duration=4)
    calls = []
    async def respond(request):
        asset.main_image = '/media/new-base.png'
        asset.metadata = {'image_gallery': ['/media/new-base.png']}
        await asset.save()
        variant.images = ['/media/new-variant.png']
        await variant.save()
        payload = json.loads(request.content)
        calls.append(payload)
        tool = next(tool['function']['name'] for tool in payload['tools'] if 'final_result' in tool['function']['name'])
        envelope = {'id': 'test-completion', 'created': 1, 'model': 'test', 'object': 'chat.completion.chunk'}
        events = [{**envelope, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0,
            'id': 'result-call', 'type': 'function', 'function': {'name': tool, 'arguments': json.dumps({'shots': [raw_shot(1), raw_shot(2)]})}}]},
            'finish_reason': 'tool_calls'}]}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=StreamBody(events, interrupted))
    with patch('services.creation_agent.handler.AsyncOpenAI', side_effect=lambda **kw: AsyncOpenAI(
            **kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))):
        task = await scene_controller.generate(chapter.id, replace_existing=replace_existing)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert await Scene.filter(chapter=chapter).count() == 2
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('finish_reason', [None, 'length', 'content_filter'])
async def test_interrupted_unconfirmed_response_never_replaces_saved_storyboard(finish_reason):
    _, chapter, _ = await enabled_project()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': 'zh'})
    old = await Scene.create(chapter=chapter, sequence=1, prompt='保留原分镜', duration=4)
    calls = []
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        tool = next(tool['function']['name'] for tool in payload['tools'] if 'final_result' in tool['function']['name'])
        events = [{'id': 'cut-response', 'created': 1, 'model': 'test', 'object': 'chat.completion.chunk',
            'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': 'result', 'type': 'function',
                'function': {'name': tool, 'arguments': json.dumps({'shots': [raw_shot(1)]})}}]},
                'finish_reason': finish_reason}]}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=StreamBody(events, True))
    with patch('services.creation_agent.handler.AsyncOpenAI', side_effect=lambda **kw: AsyncOpenAI(
            **kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))):
        task = await scene_controller.generate(chapter.id, replace_existing=True)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    from services.creation_agent.reliability import recovery_summary
    assert (await recovery_summary(task))['failure_step'] == 'storyboard'
    assert (await Scene.get(id=old.id)).prompt == '保留原分镜'
    assert await Scene.filter(chapter=chapter).count() == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_explicit_finish_does_not_bypass_invalid_storyboard_validation():
    _, chapter, _ = await enabled_project()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': 'zh'})
    old = await Scene.create(chapter=chapter, sequence=1, prompt='保留原分镜', duration=4)
    calls = []
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        tool = next(tool['function']['name'] for tool in payload['tools'] if 'final_result' in tool['function']['name'])
        events = [{'id': 'invalid-response', 'created': 1, 'model': 'test', 'object': 'chat.completion.chunk',
            'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': 'result', 'type': 'function',
                'function': {'name': tool, 'arguments': '{"shots": [{"sequence": 1}]}'}}]},
                'finish_reason': 'tool_calls'}]}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=StreamBody(events, True))
    with patch('services.creation_agent.handler.AsyncOpenAI', side_effect=lambda **kw: AsyncOpenAI(
            **kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))):
        task = await scene_controller.generate(chapter.id, replace_existing=True)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    from services.creation_agent.reliability import recovery_summary
    assert (await recovery_summary(task))['failure_step'] == 'storyboard'
    assert (await Scene.get(id=old.id)).prompt == '保留原分镜'
    assert await Scene.filter(chapter=chapter).count() == 1
    assert len(calls) <= 2
