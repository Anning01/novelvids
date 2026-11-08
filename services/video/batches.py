"""Persist sequential video submissions using the existing task recovery worker."""

from uuid import UUID, uuid5

from fastapi import HTTPException
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.scene import Scene
from models.video import Video
from schemas.video import VideoGenerateRequest, VideoReferenceMedia
from services.creation_objects import project_write
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.skill_execution import current_execution, prepare_workflow
from services.creation_agent.submissions import submit_once
from services.creation_agent.waiting import WaitingForDependencies


async def latest_batch(chapter_id):
    for task in await AiTask.filter(task_type=4, status__in=[1, 2, 6]).order_by('-created_at'):
        if task.request_params.get('operation') == 'video_batch' and task.request_params.get('chapter_id') == chapter_id:
            return task
    return None


async def submit_batch(request, *, media_base_url='', team_id=None, user_id=None):
    ids = [item.scene_id for item in request.requests]
    scenes = await Scene.filter(id__in=ids).order_by('sequence').prefetch_related('chapter')
    if len(scenes) != len(ids) or len({s.chapter_id for s in scenes}) != 1:
        raise HTTPException(422, '连续生成必须选择同一集的不重复分镜')
    if not all(item.return_last_frame for item in request.requests):
        raise HTTPException(422, '连续生成必须开启尾帧衔接')
    chapter_id = scenes[0].chapter_id
    params = await prepare_workflow({'operation': 'video_batch', 'novel_id': scenes[0].chapter.novel_id,
        'chapter_id': chapter_id, 'team_id': team_id, 'user_id': user_id, 'media_base_url': media_base_url,
        'batch_requests': [next(item for item in request.requests if item.scene_id == scene.id).model_dump(mode='json') for scene in scenes]})
    async with project_write(params['novel_id']) as connection:
        active = await latest_batch(chapter_id)
        if active:
            return active
        async def create(connection):
            return await AiTask.create(task_type=4, status=6, stage='queued', request_params=params, using_db=connection)
        return await submit_once(4, params, create)


def require_continuity(video, next_scene_id):
    metadata = video.metadata or {}
    if video.status != 3 or not video.url:
        raise ValueError(metadata.get('error') or '分镜视频未完成，后续未提交')
    enhancement = metadata.get('auto_enhancement')
    if enhancement and enhancement.get('stage') not in {'completed', 'skipped'}:
        raise ValueError('自动高清化未完成，后续未提交')
    if next_scene_id is None:
        return
    reference = metadata.get('last_frame_reference') or {}
    if (not metadata.get('last_frame_url') or metadata.get('last_frame_extraction_error')
        or metadata.get('last_frame_propagation_error')
        or metadata.get('last_frame_source') not in {'provider', 'ffmpeg'}
        or metadata.get('last_frame_injected_scene_id') != next_scene_id
        or reference.get('url') != metadata['last_frame_url']
        or not metadata.get('last_frame_prompt_instruction')):
        raise ValueError('上一镜头尾帧衔接未完成，后续未提交')


class VideoBatchHandler:
    async def execute(self, params):
        from services.creation_agent.video_jobs import submit_video
        execution = current_execution.get()
        requests = params['batch_requests']
        videos = []
        for index, raw in enumerate(requests):
            await execution.before_request()
            req = VideoGenerateRequest.model_validate(raw)
            request_id = uuid5(UUID(params['task_id']), f'video:{req.scene_id}')
            key = 'submit:' + str(request_id)
            receipt = await AgentOperation.get_or_none(task_id=params['task_id'], key=key, state='completed')
            if receipt is None:
                scene = await Scene.get(id=req.scene_id)
                references = list(req.reference_media)
                for item in (scene.metadata or {}).get('video_reference_media', []):
                    if item.get('source') != 'previous_scene_last_frame':
                        continue
                    reference = VideoReferenceMedia.model_validate({k:v for k,v in item.items() if k in VideoReferenceMedia.model_fields})
                    if req.generation_mode == 'keyframes':
                        req = req.model_copy(update={'first_frame_url': reference.url})
                        continue
                    if not any((value.mention_url or value.url) == (reference.mention_url or reference.url) for value in references):
                        references.append(reference)
                req = req.model_copy(update={'request_id': request_id, 'reference_media': references})
                async def submit():
                    video = await submit_video(req, media_base_url=params.get('media_base_url', ''),
                        team_id=params.get('team_id'), user_id=params.get('user_id'))
                    return {'video_id': video.id, 'task_id': video.metadata['agent_run_id']}
                result = await execute_step(params['task_id'], key, submit, atomic=True)
            else:
                result = receipt.result
            video = await Video.get(id=result['video_id'])
            videos.append(video.id)
            await AiTask.filter(id=params['task_id']).update(progress=round(index / len(requests) * 100),
                response_data={'video_ids': videos, 'completed_count': index, 'total': len(requests)})
            if video.status in {1, 2, 6}:
                raise WaitingForDependencies()
            require_continuity(video, requests[index + 1]['scene_id'] if index + 1 < len(requests) else None)
        await AiTask.filter(id=params['task_id']).update(progress=100)
        return {'video_ids': videos, 'completed_count': len(requests), 'total': len(requests)}
