"""仪表盘 API 端点。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from novelvids.api.dependencies import (
    get_current_user,
    get_novel_repository,
    get_user_repository,
    get_video_repository,
)
from novelvids.application.dto import NovelResponseDTO
from novelvids.application.dto.dashboard import DashboardStatsDTO
from novelvids.infrastructure.database.repositories import (
    TortoiseNovelRepository,
    TortoiseUserRepository,
    TortoiseVideoRepository,
)
from novelvids.infrastructure.database.models import UserModel

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/stats", response_model=DashboardStatsDTO)
async def get_dashboard_stats(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    video_repo: Annotated[TortoiseVideoRepository, Depends(get_video_repository)],
    user_repo: Annotated[TortoiseUserRepository, Depends(get_user_repository)],
) -> DashboardStatsDTO:
    """获取当前用户的仪表盘统计信息。"""
    # 获取用户的小说
    novels = await novel_repo.get_by_user_id(current_user.id)
    total_novels = len(novels)

    # 获取最近的小说（按创建时间降序排列前 5 个）
    # 由于 get_by_user_id 可能默认不支持排序，
    # 我们暂时在 Python 中排序，或者使用过滤（如果可用）。
    # 理想情况下，仓库应该支持排序。
    sorted_novels = sorted(novels, key=lambda n: n.created_at, reverse=True)
    recent_novels = [NovelResponseDTO.model_validate(n) for n in sorted_novels[:5]]

    # 获取用户的视频
    # 我们需要遍历小说，或者使用直接查询（如果视频有 user_id 关联的话，它没有，只能通过 novel）
    # TortoiseORM 允许通过关联字段过滤。
    # 但是，仓库接口抽象可能需要为每个小说通过 novel_id 查找视频。
    # 为了效率，我们希望有一个专门的查询，但现在我们坚持使用仓库模式。
    total_videos = 0
    total_duration_seconds = 0.0

    # 这是 n+1 查询，对于大规模不太理想，但对于 MVP 来说可以接受
    for novel in novels:
        videos = await video_repo.get_by_novel_id(novel.id)
        total_videos += len(videos)
        for video in videos:
            total_duration_seconds += video.duration

    processing_time_hours = total_duration_seconds / 3600

    return DashboardStatsDTO(
        total_novels=total_novels,
        total_videos=total_videos,
        processing_time=round(processing_time_hours, 2),
        balance=float(current_user.balance),
        recent_novels=recent_novels,
    )
