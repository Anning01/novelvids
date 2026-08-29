from fastapi import APIRouter, Depends, HTTPException, Query

from auth.deps import AuthContext, ensure_novel_access, get_auth_context
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from models.video import Video
from schemas.workbench import WorkbenchBootstrapOut, WorkbenchCapabilitiesOut
from services.oss import oss
from utils.response_format import ResponseSchema

router = APIRouter()


@router.get(
    "/capabilities",
    summary="获取创作画布能力",
    response_model=ResponseSchema[WorkbenchCapabilitiesOut],
)
async def get_workbench_capabilities(
    _: AuthContext = Depends(get_auth_context),
):
    return ResponseSchema(data=WorkbenchCapabilitiesOut())


@router.get(
    "/bootstrap",
    summary="加载当前章节画布工作集",
    response_model=ResponseSchema[WorkbenchBootstrapOut],
)
async def get_workbench_bootstrap(
    novel_id: int = Query(..., ge=1),
    chapter_id: int = Query(..., ge=1),
    ctx: AuthContext = Depends(get_auth_context),
):
    await ensure_novel_access(novel_id, ctx)
    novel = await Novel.get_or_none(id=novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    chapter = await Chapter.get_or_none(id=chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.novel_id != novel_id:
        raise HTTPException(status_code=400, detail="章节不属于当前项目")

    scenes = await Scene.filter(chapter_id=chapter.id).order_by("sequence").prefetch_related("assets")
    linked_asset_ids = {
        asset.id
        for scene in scenes
        for asset in scene.assets
    }
    # source_chapters 是 JSON 数组。先只扫描轻量字段，再只读取当前章节真正
    # 需要的完整资产与形态，避免项目资产很多时把全部图片和 variants 拉进内存。
    project_asset_sources = await Asset.filter(novel_id=novel_id).values(
        "id",
        "source_chapters",
    )
    relevant_asset_ids = linked_asset_ids | {
        item["id"]
        for item in project_asset_sources
        if chapter.number in (item["source_chapters"] or [])
    }
    assets = (
        await Asset.filter(id__in=relevant_asset_ids)
        .order_by("id")
        .prefetch_related("variants")
        if relevant_asset_ids
        else []
    )

    scene_ids = [scene.id for scene in scenes]
    videos = await Video.filter(scene_id__in=scene_ids).order_by("-id") if scene_ids else []
    videos_by_scene: dict[int, list[Video]] = {scene_id: [] for scene_id in scene_ids}
    for video in videos:
        videos_by_scene.setdefault(video.scene_id, []).append(video)

    remake_source = None
    if novel.workflow_kind == "remake":
        source = await RemakeSource.get_or_none(
            novel_id=novel_id,
            chapter_id=chapter.id,
        ).select_related("analysis_task")
        if source is not None:
            media_url = (
                f"/media/{source.object_key}"
                if source.storage_provider == "local"
                else oss.resolve_url(source.object_key) or source.object_key
            )
            task = source.analysis_task
            remake_source = {
                "id": source.id,
                "episode_number": source.episode_number,
                "source_kind": source.source_kind,
                "media_url": media_url,
                "original_filename": source.original_filename,
                "mime_type": source.mime_type,
                "size_bytes": source.size_bytes,
                "duration_seconds": source.duration_seconds,
                "width": source.width,
                "height": source.height,
                "media_status": source.media_status,
                "analysis_task": (
                    {
                        "id": task.id,
                        "status": task.status,
                        "stage": task.stage,
                        "progress": task.progress,
                        "error_message": task.error_message,
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                    }
                    if task is not None
                    else None
                ),
            }

    payload = WorkbenchBootstrapOut.model_validate(
        {
            "chapter": chapter,
            "project_config": {
                "workflow_kind": novel.workflow_kind,
                "aspect_ratio": novel.aspect_ratio,
                "resolution": novel.resolution,
                "style_key": novel.style_key,
                "custom_style_prompt": novel.custom_style_prompt,
            },
            "remake_source": remake_source,
            "assets": assets,
            "scenes": scenes,
            "videos": videos_by_scene,
        }
    )
    return ResponseSchema[WorkbenchBootstrapOut](data=payload)
