from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException

from auth.deps import (
    AuthContext,
    ensure_novel_access,
    get_auth_context,
    require_roles,
    require_scene_access,
)
from controllers.scene import scene_controller
from models.chapter import Chapter
from models.scene import Scene
from schemas.scene import (
    SceneBriefOut,
    SceneCreate,
    SceneGenerateCreate,
    SceneOut,
    ScenePatch,
    SceneUpdate,
    StoryboardStrategyOut,
)
from schemas.ai_task import AiTaskOut
from services.ai_task_executor import ai_task_executor
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema
from services.storyboard.strategies import storyboard_strategy_factory

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))


async def _ensure_chapter_team_access(chapter_id: int, ctx: AuthContext) -> None:
    chapter = await Chapter.get_or_none(id=chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    await ensure_novel_access(chapter.novel_id, ctx)


@router.post("/generate/", summary="AI生成分镜", response_model=ResponseSchema[AiTaskOut])
async def generate_scene(
    generate_data: SceneGenerateCreate,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    """提交分镜生成任务，返回任务记录供前端轮询"""
    await _ensure_chapter_team_access(generate_data.chapter_id, ctx)
    task = await scene_controller.generate(
        generate_data.chapter_id,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    background_tasks.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.get(
    "/strategies",
    summary="获取可用分镜策略",
    response_model=ResponseSchema[list[StoryboardStrategyOut]],
)
async def get_storyboard_strategies(
    _: AuthContext = Depends(get_auth_context),
):
    default_key = storyboard_strategy_factory.default.key
    strategies = [
        StoryboardStrategyOut(
            key=strategy.key,
            name=strategy.name,
            description=strategy.description,
            is_default=strategy.key == default_key,
        )
        for strategy in storyboard_strategy_factory.list()
    ]
    return ResponseSchema(data=strategies)


@router.post("/", summary="手动创建分镜", response_model=ResponseSchema[SceneOut])
async def create_scene(
    scene: SceneCreate,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await _ensure_chapter_team_access(scene.chapter_id, ctx)
    task = await scene_controller.create(scene)
    return ResponseSchema(data=task)


@router.post("/{scene_id}/insert-after", summary="在指定分镜后添加分镜", response_model=ResponseSchema[SceneOut])
async def insert_scene_after(
    scene_id: int,
    _: AuthContext = Depends(require_scene_access),
    __: AuthContext = _EDITOR,
):
    scene = await scene_controller.insert_after(scene_id)
    return ResponseSchema(data=scene)


@router.put("/{scene_id}", summary="全量修改分镜", response_model=ResponseSchema[SceneOut])
async def update_scene(
    scene_id: int,
    scene: SceneUpdate,
    _: AuthContext = Depends(require_scene_access),
    __: AuthContext = _EDITOR,
):
    scenes = await scene_controller.update(scene_id, scene)
    return ResponseSchema(data=scenes)


@router.patch("/{scene_id}", summary="局部更新分镜", response_model=ResponseSchema[SceneOut])
async def patch_scene(
    scene_id: int,
    scene: ScenePatch,
    _: AuthContext = Depends(require_scene_access),
    __: AuthContext = _EDITOR,
):
    scenes = await scene_controller.patch(scene_id, scene)
    return ResponseSchema(data=scenes)


@router.get(
    "", summary="获取分镜列表", response_model=ResponseSchema[PaginationResponse[SceneBriefOut]]
)
async def get_scene_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
):
    base_query = None
    if ctx.team_id is not None:
        base_query = Scene.filter(chapter__novel__team_id=ctx.team_id)
    scenes = await scene_controller.list(params, SceneBriefOut, base_query=base_query)
    return ResponseSchema(data=scenes)


@router.get(
    "/{scene_id}", summary="获取分镜详情", response_model=ResponseSchema[SceneOut]
)
async def get_scene(
    scene_id: int,
    _: AuthContext = Depends(require_scene_access),
):
    scene = await scene_controller._get_with_assets(scene_id)
    return ResponseSchema(data=scene)


@router.delete(
    "/{scene_id}", summary="删除一个分镜", response_model=ResponseSchema
)
async def delete_scene(
    scene_id: int,
    _: AuthContext = Depends(require_scene_access),
    __: AuthContext = _EDITOR,
):
    await scene_controller.remove(scene_id)
    return ResponseSchema()
