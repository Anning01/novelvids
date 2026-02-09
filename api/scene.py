from fastapi import APIRouter, Depends, BackgroundTasks

from controllers.scene import scene_controller
from schemas.scene import SceneBriefOut, SceneUpdate, ScenePatch, SceneOut
from schemas.ai_task import AiTaskOut
from services.ai_task_executor import ai_task_executor
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("/generate/{chapter_id}", summary="生成分镜", response_model=ResponseSchema[AiTaskOut])
async def create_scene(chapter_id: int, background_tasks: BackgroundTasks):
    """提交分镜生成任务，返回任务记录供前端轮询"""
    task = await scene_controller.create(chapter_id)
    background_tasks.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.put("/{scene_id}", summary="全量修改分镜", response_model=ResponseSchema[SceneOut])
async def update_scene(scene_id: int, scene: SceneUpdate):
    scenes = await scene_controller.update(scene_id, scene)
    return ResponseSchema(data=scenes)


@router.patch("/{scene_id}", summary="局部更新分镜", response_model=ResponseSchema[SceneOut])
async def patch_scene(scene_id: int, scene: ScenePatch):
    scenes = await scene_controller.patch(scene_id, scene)
    return ResponseSchema(data=scenes)


@router.get(
    "", summary="获取分镜列表", response_model=ResponseSchema[PaginationResponse[SceneBriefOut]]
)
async def get_scene_list(params: QueryParams = Depends(get_list_params)):
    scenes = await scene_controller.list(params, SceneBriefOut)
    return ResponseSchema(data=scenes)


@router.get(
    "/{scene_id}", summary="获取分镜详情", response_model=ResponseSchema[SceneOut]
)
async def get_scene(scene_id: int):
    scene = await scene_controller.get(scene_id)
    return ResponseSchema(data=scene)


@router.delete(
    "/{scene_id}", summary="删除一个分镜", response_model=ResponseSchema
)
async def delete_scene(scene_id: int):
    await scene_controller.remove(scene_id)
    return ResponseSchema()
