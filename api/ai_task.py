from uuid import UUID

from fastapi import APIRouter, Depends

from auth.deps import AuthContext, require_roles, require_task_access
from controllers.ai_task import ai_task_controller
from schemas.ai_task import AiTaskOut, TaskReviewResolution
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


@router.post(
    "/{task_id}/review",
    summary="人工核对并收口不明确的外部提交",
    response_model=ResponseSchema[AiTaskOut],
)
async def review_task(
    task_id: UUID,
    resolution: TaskReviewResolution,
    ctx: AuthContext = Depends(require_task_access),
    _: AuthContext = _EDITOR,
):
    from services.creation_agent.review import close_uncertain_task

    task = await close_uncertain_task(
        task_id, resolution, user_id=ctx.user.id if ctx.user else None
    )
    return ResponseSchema(data=task)
