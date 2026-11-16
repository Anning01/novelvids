from uuid import UUID

from fastapi import APIRouter, Depends

from auth.deps import AuthContext, require_roles, require_task_access
from controllers.ai_task import ai_task_controller
from schemas.ai_task import AiTaskOut
from utils.response_format import ResponseSchema

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))


@router.get(
    "/{task_id}", summary="查询任务状态", response_model=ResponseSchema[AiTaskOut]
)
async def get_task(
    task_id: UUID,
    _: AuthContext = Depends(require_task_access),
):
    task = await ai_task_controller.get(task_id)
    return ResponseSchema(data=task)


@router.post(
    "/{task_id}/cancel", summary="取消任务", response_model=ResponseSchema[AiTaskOut]
)
async def cancel_task(
    task_id: UUID,
    _: AuthContext = Depends(require_task_access),
    __: AuthContext = _EDITOR,
):
    task = await ai_task_controller.cancel(task_id)
    return ResponseSchema(data=task)


@router.post('/{task_id}/retry', summary='重置失败任务并继续未完成步骤', response_model=ResponseSchema[AiTaskOut])
async def retry_task(task_id: UUID, ctx: AuthContext = Depends(require_task_access), _: AuthContext = _EDITOR):
    from services.media_tasks import is_media_task, retry_media_task
    task = await ai_task_controller.get(task_id)
    if is_media_task(task.request_params):
        return ResponseSchema(data=await retry_media_task(task))
    from services.creation_agent.production_resume import resume_production
    return ResponseSchema(data=await resume_production(task_id, ctx))
