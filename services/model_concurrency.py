"""Share each configured model's request capacity across task entry points."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

from models.config import AiModelConfig


# A caller may publish a real queue transition without changing the shared model limit.
capacity_observer = ContextVar("capacity_observer", default=None)


class ModelSlots:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = {}
        self.limits = {}

    @asynccontextmanager
    async def hold(self, model_id):
        if model_id is None:
            yield
            return
        config = await AiModelConfig.filter(id=model_id).only('id', 'concurrency').first()
        if config is None:
            # The caller retains its existing unavailable-model validation and failure handling.
            yield
            return
        observer = capacity_observer.get()
        announced = False
        async with self.condition:
            self.limits[model_id] = max(1, config.concurrency)
            self.condition.notify_all()
        while True:
            async with self.condition:
                if self.active.get(model_id, 0) < self.limits[model_id]:
                    self.active[model_id] = self.active.get(model_id, 0) + 1
                    break
                if not observer or announced:
                    await self.condition.wait()
                    continue
            announced = True
            await observer("waiting_capacity")
        try:
            if announced:
                await observer("admitted")
            yield
        finally:
            async with self.condition:
                self.active[model_id] -= 1
                self.condition.notify_all()


model_slots = ModelSlots()


async def claim_task(task, **values):
    """Asynchronous video jobs retain a model slot while the provider is working."""
    from models.ai_task import AiTask
    from models.video import Video
    from tortoise.transactions import in_transaction
    from tortoise.expressions import F
    params = task.request_params
    if params.get('operation') != 'video' or not params.get('model_config_id'):
        return await AiTask.filter(id=task.id, status__in=[1, 6]).update(**values)
    async with in_transaction() as db:
        model_id = params['model_config_id']
        await AiModelConfig.filter(id=model_id).using_db(db).update(concurrency=F('concurrency'))
        config = await AiModelConfig.filter(id=model_id).using_db(db).select_for_update().first()
        if config:
            running = [row for row in await AiTask.filter(task_type=4, status=2).exclude(id=task.id).using_db(db)
                       if row.request_params.get('operation') == 'video' and row.request_params.get('model_config_id') == model_id]
            videos = {video.id: video for video in await Video.filter(id__in=[row.request_params['video_id'] for row in running if row.request_params.get('video_id')]).using_db(db)}
            # Accepted provider jobs still occupy capacity even if their parent was cancelled.
            accepted = [video for video in await Video.filter(status__in=[1, 2]).using_db(db)
                        if (video.metadata or {}).get('model_config_id') == model_id]
            accepted_ids = {video.id for video in accepted}
            occupied = len(accepted)
            for row in running:
                video = videos.get(row.request_params.get('video_id'))
                if video is None or (video.id not in accepted_ids and video.status in {1, 2, 6}):
                    occupied += 1
            if occupied >= config.concurrency:
                await AiTask.filter(id=task.id, status__in=[1, 6]).using_db(db).update(status=6, stage='waiting_capacity')
                return 0
        return await AiTask.filter(id=task.id, status__in=[1, 6]).using_db(db).update(**values)
