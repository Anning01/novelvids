from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from models.ai_task import AiTask
from models.scene import Scene
from models.video import Video
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.waiting import WaitingForDependencies
from services.video.batches import VideoBatchHandler, submit_batch
from schemas.video import VideoBatchGenerateRequest, VideoGenerateRequest
from test.test_services.test_skill_workflow import enabled_project


async def batch_fixture():
    project, chapter, _ = await enabled_project()
    scenes = [await Scene.create(chapter=chapter, sequence=i, prompt=f'Scene {i}') for i in range(1, 6)]
    request = VideoBatchGenerateRequest(requests=[VideoGenerateRequest(scene_id=s.id, model_config_id=1,
        return_last_frame=True) for s in scenes])
    task = await submit_batch(request)
    await AiTask.filter(id=task.id).update(status=2)
    return task, scenes, request


@pytest.mark.asyncio
async def test_batch_survives_handler_restarts_and_submits_all_five_once(monkeypatch):
    task, scenes, request = await batch_fixture()
    sent = []
    async def submit(req, **kwargs):
        sent.append(req)
        child = await AiTask.create(task_type=4, status=2)
        return await Video.create(scene_id=req.scene_id, model_type=1, status=2,
            metadata={'agent_run_id': str(child.id)})
    monkeypatch.setattr('services.creation_agent.video_jobs.submit_video', submit)
    assert (await submit_batch(request)).id == task.id
    token = current_execution.set(SimpleNamespace(before_request=AsyncMock()))
    params = {**task.request_params, 'task_id': str(task.id)}
    try:
        for index, scene in enumerate(scenes):
            with pytest.raises(WaitingForDependencies):
                await VideoBatchHandler().execute(params)
            with pytest.raises(WaitingForDependencies):
                await VideoBatchHandler().execute(params)
            assert len(sent) == index + 1
            video = await Video.get(scene=scene)
            frame = f'https://cdn.example.com/tail-{index}.png'
            metadata = {**video.metadata, 'last_frame_url': frame, 'last_frame_source': 'provider'}
            if index + 1 < len(scenes):
                reference = {'type':'image','url':frame,'source':'previous_scene_last_frame'}
                metadata.update(last_frame_injected_scene_id=scenes[index+1].id,
                    last_frame_reference=reference,last_frame_prompt_instruction='frame reference')
                await Scene.filter(id=scenes[index+1].id).update(metadata={'video_reference_media':[reference]})
            await Video.filter(id=video.id).update(status=3,url=f'https://cdn.example.com/video-{index}.mp4',metadata=metadata)
            await AiTask.filter(id=video.metadata['agent_run_id']).update(status=3)
        result = await VideoBatchHandler().execute(params)
        assert result['completed_count'] == 5
        assert [item.scene_id for item in sent] == [s.id for s in scenes]
        assert all(item.reference_media for item in sent[1:])
        assert len({item.request_id for item in sent}) == 5
        assert (await VideoBatchHandler().execute(params))['completed_count'] == 5
        assert len(sent) == 5
    finally: current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['failed', 'uncertain', 'missing_tail'])
async def test_batch_stops_before_second_submission_on_failure(monkeypatch, failure):
    task, scenes, _ = await batch_fixture()
    child = await AiTask.create(task_type=4,status=4)
    video = await Video.create(scene=scenes[0],model_type=1,status=3 if failure=='missing_tail' else 4,
        url='https://cdn.example.com/first.mp4' if failure=='missing_tail' else None,
        metadata={'agent_run_id':str(child.id),'submission_uncertain':failure=='uncertain','error':'not completed'})
    submit = AsyncMock(return_value=video)
    monkeypatch.setattr('services.creation_agent.video_jobs.submit_video',submit)
    token=current_execution.set(SimpleNamespace(before_request=AsyncMock()))
    try:
        with pytest.raises(ValueError):
            await VideoBatchHandler().execute({**task.request_params,'task_id':str(task.id)})
        submit.assert_awaited_once()
        assert submit.call_args.args[0].scene_id==scenes[0].id
    finally: current_execution.reset(token)


@pytest.mark.asyncio
async def test_batch_runs_with_existing_executor_without_a_model_call(monkeypatch):
    from services.ai_task_executor import ai_task_executor
    task, scenes, _ = await batch_fixture()
    await AiTask.filter(id=task.id).update(status=6)
    child=await AiTask.create(task_type=4,status=2)
    video=await Video.create(scene=scenes[0],model_type=1,status=2,metadata={'agent_run_id':str(child.id)})
    submit=AsyncMock(return_value=video)
    monkeypatch.setattr('services.creation_agent.video_jobs.submit_video',submit)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.stage=='waiting_dependencies'
    assert task.response_data['video_ids']==[video.id]
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_api_persists_all_selected_scenes_and_exposes_recovery_status(client):
    task, scenes, request = await batch_fixture()
    response = await client.post('/api/video/batch', json=request.model_dump(mode='json'))
    assert response.status_code == 200
    assert response.json()['data']['id'] == str(task.id)
    latest = await client.get(f'/api/video/batch/latest/{scenes[0].chapter_id}')
    assert latest.json()['data']['id'] == str(task.id)
    assert len(latest.json()['data']['request_params']['batch_requests']) == 5
    assert await Video.all().count() == 0


@pytest.mark.asyncio
async def test_batch_rejects_duplicate_scenes_before_scheduling():
    from fastapi import HTTPException
    task, scenes, request = await batch_fixture()
    request.requests.append(request.requests[0])
    before = await AiTask.all().count()
    with pytest.raises(HTTPException):
        await submit_batch(request)
    assert await AiTask.all().count() == before
