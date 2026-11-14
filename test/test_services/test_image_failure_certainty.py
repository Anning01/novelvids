from unittest.mock import AsyncMock
import httpx
import pytest

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from services.creation_agent.operation_receipts import execute_step
from services.image_generation.gateway import ImageGenerationError, generate_images
from services.ai_task_executor import AiTaskExecutor


@pytest.mark.parametrize('status,uncertain', [(400, False), (422, False), (429, False), (408, True), (500, True)])
async def test_known_rejection_preserves_error_without_uncertain_receipt(monkeypatch, status, uncertain):
    client = httpx.AsyncClient
    monkeypatch.setattr('services.image_generation.gateway.httpx.AsyncClient', lambda **kw: client(**kw,
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json={
            'error': {'code': 'bad_request', 'message': 'Specific supplier rejection secret-key'}},
            headers={'x-request-id': 'receipt-test'}))))
    task = await AiTask.create(task_type=2, status=2, request_params={'workflow_version': 'agent-skills-v1', 'prompt_language': 'zh'})
    async def invoke():
        return await generate_images(base_url='https://example.invalid', api_key='secret-key', model='model', prompt='design')
    with pytest.raises(ImageGenerationError) as raised:
        await execute_step(task.id, 'media:image', invoke, external=True)
    error = raised.value
    assert error.submission_uncertain is uncertain
    assert 'secret-key' not in str(error) and 'Specific supplier rejection' in str(error)
    receipt = await AgentOperation.get(task=task, key='media:image')
    assert receipt.state == ('uncertain' if uncertain else 'failed')
    executor = AiTaskExecutor()
    await executor._fail(task, str(error), error=error, record_usage=False)
    await task.refresh_from_db()
    assert 'Specific supplier rejection' in task.error_message
    assert ('结果待核对' in task.error_message) is uncertain
    assert (task.stage == 'needs_review') is uncertain


async def test_timeout_remains_uncertain_and_cannot_be_replayed():
    task = await AiTask.create(task_type=2, status=2, request_params={})
    call = AsyncMock(side_effect=ImageGenerationError('Network timeout'))
    with pytest.raises(ImageGenerationError):
        await execute_step(task.id, 'media:image', call, external=True)
    from services.creation_agent.operation_receipts import SubmissionUncertain
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, 'media:image', call, external=True)
    assert call.await_count == 1


async def test_rejection_after_an_earlier_image_does_not_allow_replaying_the_whole_batch(monkeypatch):
    from services.reference.generator import generate_for_sora_consistency
    from services.image_generation.gateway import GeneratedImage
    error = ImageGenerationError('Second image rejected', submission_uncertain=False)
    monkeypatch.setattr('services.reference.generator.generate_images', AsyncMock(side_effect=[
        [GeneratedImage(url='https://example.invalid/first.png')], error]))
    with pytest.raises(ImageGenerationError) as raised:
        await generate_for_sora_consistency({'base_traits': 'design'}, base_url='https://example.invalid',
            api_key='test', count=2)
    assert raised.value.submission_uncertain
