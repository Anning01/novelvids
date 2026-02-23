from uuid import UUID

from fastapi import APIRouter

from controllers.ai_task import ai_task_controller
from schemas.ai_task import AiTaskOut
from utils.response_format import ResponseSchema

router = APIRouter()


@router.get(
    "/{task_id}", summary="查询任务状态", response_model=ResponseSchema[AiTaskOut]
)
async def get_task(task_id: UUID):
    task = await ai_task_controller.get(task_id)
    return ResponseSchema(data=task)


@router.post(
    "/{task_id}/cancel", summary="取消任务", response_model=ResponseSchema[AiTaskOut]
)
async def cancel_task(task_id: UUID):
    task = await ai_task_controller.cancel(task_id)
    return ResponseSchema(data=task)
