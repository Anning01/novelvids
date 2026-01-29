"""资产相关的 API 端点。"""

import uuid as uuid_module
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from novelvids.api.dependencies import (
    get_current_user_id,
    get_novel_repository,
)
from novelvids.application.dto import (
    AssetCreateDTO,
    AssetResponseDTO,
    AssetUpdateDTO,
    PaginatedResponseDTO,
)
from novelvids.core.config import settings
from novelvids.infrastructure.database.models import AssetModel, AssetType
from novelvids.infrastructure.database.repositories import (
    TortoiseAssetRepository,
    TortoiseNovelRepository,
)

router = APIRouter(prefix="/novels/{novel_id}/assets", tags=["资产库"])


def get_asset_repository() -> TortoiseAssetRepository:
    """获取资产仓库实例。"""
    return TortoiseAssetRepository()


async def verify_novel_access(
    novel_id: UUID,
    user_id: UUID,
    novel_repo: TortoiseNovelRepository,
) -> None:
    """验证用户是否有权限访问该小说。"""
    novel = await novel_repo.get_by_id(novel_id)
    if novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="小说不存在")
    if novel.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="拒绝访问")


@router.get("", response_model=PaginatedResponseDTO[AssetResponseDTO])
async def list_assets(
    novel_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
    asset_type: str | None = Query(None, description="Filter by asset type: person, scene, item"),
    is_global: bool | None = Query(None, description="Filter by global status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出小说的所有资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    # Build filters
    filters = {"novel_id": novel_id}
    if asset_type:
        filters["asset_type"] = asset_type
    if is_global is not None:
        filters["is_global"] = is_global

    # Get paginated results
    skip = (page - 1) * page_size
    assets = await asset_repo.get_all(skip=skip, limit=page_size, filters=filters)
    total = await asset_repo.count(filters=filters)

    return PaginatedResponseDTO(
        items=[AssetResponseDTO.model_validate(a) for a in assets],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=AssetResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_asset(
    novel_id: UUID,
    data: AssetCreateDTO,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """创建新资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    # Validate asset_type
    if data.asset_type not in [t.value for t in AssetType]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid asset type. Must be one of: {[t.value for t in AssetType]}",
        )

    # Check if asset already exists
    existing = await asset_repo.get_by_name(novel_id, data.canonical_name, data.asset_type)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该类型的同名资产已存在",
        )

    asset = await asset_repo.create(novel_id=novel_id, **data.model_dump())
    return AssetResponseDTO.model_validate(asset)


# NOTE: Static path routes must be defined BEFORE dynamic path routes
# Otherwise /global and /by-type/... will be matched by /{asset_id}

@router.get("/global", response_model=list[AssetResponseDTO])
async def list_global_assets(
    novel_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
    asset_type: str | None = Query(None),
):
    """列出全局资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)
    assets = await asset_repo.get_global_assets(novel_id, asset_type)
    return [AssetResponseDTO.model_validate(a) for a in assets]


@router.get("/by-type/{asset_type}", response_model=list[AssetResponseDTO])
async def list_assets_by_type(
    novel_id: UUID,
    asset_type: str,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """按类型列出资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    if asset_type not in [t.value for t in AssetType]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid asset type. Must be one of: {[t.value for t in AssetType]}",
        )

    assets = await asset_repo.get_by_novel_id(novel_id, asset_type)
    return [AssetResponseDTO.model_validate(a) for a in assets]


@router.get("/{asset_id}", response_model=AssetResponseDTO)
async def get_asset(
    novel_id: UUID,
    asset_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """获取特定资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    asset = await asset_repo.get_by_id(asset_id)
    if asset is None or asset.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")

    return AssetResponseDTO.model_validate(asset)


@router.put("/{asset_id}", response_model=AssetResponseDTO)
async def update_asset(
    novel_id: UUID,
    asset_id: UUID,
    data: AssetUpdateDTO,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """更新资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    asset = await asset_repo.get_by_id(asset_id)
    if asset is None or asset.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")

    update_data = data.model_dump(exclude_unset=True)
    updated = await asset_repo.update(asset_id, update_data)
    return AssetResponseDTO.model_validate(updated)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    novel_id: UUID,
    asset_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """删除资产。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    asset = await asset_repo.get_by_id(asset_id)
    if asset is None or asset.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")

    await asset_repo.delete(asset_id)


@router.post("/{asset_id}/merge/{target_id}", response_model=AssetResponseDTO)
async def merge_assets(
    novel_id: UUID,
    asset_id: UUID,
    target_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
):
    """合并两个资产（将 asset_id 合并到 target_id）。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    source = await asset_repo.get_by_id(asset_id)
    target = await asset_repo.get_by_id(target_id)

    if source is None or source.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="源资产不存在")
    if target is None or target.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标资产不存在")
    if source.asset_type != target.asset_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能合并相同类型的资产",
        )

    # Merge aliases
    merged_aliases = list(set(target.aliases + source.aliases + [source.canonical_name]))
    if target.canonical_name in merged_aliases:
        merged_aliases.remove(target.canonical_name)

    # Merge source_chapters
    merged_chapters = list(set(target.source_chapters + source.source_chapters))

    # Update target
    await asset_repo.update(
        target_id,
        {
            "aliases": merged_aliases,
            "source_chapters": sorted(merged_chapters),
            "description": target.description or source.description,
            "base_traits": target.base_traits or source.base_traits,
        },
    )

    # Delete source
    await asset_repo.delete(asset_id)

    updated = await asset_repo.get_by_id(target_id)
    return AssetResponseDTO.model_validate(updated)


@router.post("/{asset_id}/upload-image", response_model=AssetResponseDTO)
async def upload_asset_image(
    novel_id: UUID,
    asset_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
    file: UploadFile = File(...),
    image_field: str = Query("main_image", description="Image field: main_image, angle_image_1, angle_image_2"),
):
    """上传资产图片。"""
    await verify_novel_access(novel_id, user_id, novel_repo)

    asset = await asset_repo.get_by_id(asset_id)
    if asset is None or asset.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")

    # Validate image_field
    valid_fields = ["main_image", "angle_image_1", "angle_image_2"]
    if image_field not in valid_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image field. Must be one of: {valid_fields}",
        )

    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image",
        )

    # Create directory structure: media/novels/{novel_id}/assets/{asset_id}/
    media_dir = Path(settings.storage.media_dir)
    asset_dir = media_dir / "novels" / str(novel_id) / "assets" / str(asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    file_ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{image_field}_{uuid_module.uuid4().hex[:8]}{file_ext}"
    file_path = asset_dir / filename

    # Save file
    content = await file.read()
    file_path.write_bytes(content)

    # Generate URL path (relative to media mount)
    image_url = f"/media/novels/{novel_id}/assets/{asset_id}/{filename}"

    # Update asset
    updated = await asset_repo.update(asset_id, {image_field: image_url, "image_source": "upload"})
    return AssetResponseDTO.model_validate(updated)


@router.post("/{asset_id}/generate-image", response_model=AssetResponseDTO)
async def generate_asset_image_endpoint(
    novel_id: UUID,
    asset_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    asset_repo: Annotated[TortoiseAssetRepository, Depends(get_asset_repository)],
    image_field: str = Query("main_image", description="Image field: main_image, angle_image_1, angle_image_2"),
):
    """使用 AI 生成资产图片。"""
    from novelvids.domain.services.image_generation import generate_asset_image, download_and_save_image

    await verify_novel_access(novel_id, user_id, novel_repo)

    asset = await asset_repo.get_by_id(asset_id)
    if asset is None or asset.novel_id != novel_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")

    # Validate image_field
    valid_fields = ["main_image", "angle_image_1", "angle_image_2"]
    if image_field not in valid_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image field. Must be one of: {valid_fields}",
        )

    # Check if base_traits is available
    if not asset.base_traits:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="资产缺少 base_traits，无法生成图像。请先填写英文视觉特征。",
        )

    # Collect reference images for consistency (if main_image exists and generating angle images)
    reference_images = []
    if image_field != "main_image" and asset.main_image:
        # Use main image as reference for angle images
        if asset.main_image.startswith("/media/"):
            # Convert relative path to full URL for the AI service
            # The AI service needs an accessible URL, not a local path
            pass  # Skip local references for now, AI service needs public URLs
        elif asset.main_image.startswith("http"):
            reference_images.append(asset.main_image)

    # Generate image using AI
    generated_url = await generate_asset_image(
        asset_type=asset.asset_type,
        canonical_name=asset.canonical_name,
        base_traits=asset.base_traits,
        description=asset.description,
        reference_images=reference_images if reference_images else None,
    )

    if not generated_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 图像生成失败，请稍后重试",
        )

    # Download and save the image locally
    media_dir = Path(settings.storage.media_dir)
    asset_dir = media_dir / "novels" / str(novel_id) / "assets" / str(asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{image_field}_{uuid_module.uuid4().hex[:8]}.jpg"
    file_path = asset_dir / filename

    success = await download_and_save_image(generated_url, str(file_path))
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图像下载保存失败",
        )

    # Generate URL path (relative to media mount)
    image_url = f"/media/novels/{novel_id}/assets/{asset_id}/{filename}"

    # Update asset
    updated = await asset_repo.update(asset_id, {image_field: image_url, "image_source": "ai"})
    return AssetResponseDTO.model_validate(updated)
