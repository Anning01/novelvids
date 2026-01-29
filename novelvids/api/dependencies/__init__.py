"""FastAPI 的 API 依赖项。"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from novelvids.core.exceptions import AuthenticationError
from novelvids.core.security import verify_access_token
from novelvids.infrastructure.database.repositories import TortoiseUserRepository

security = HTTPBearer()


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> UUID:
    """从 JWT 令牌中获取当前用户 ID。"""
    try:
        payload = verify_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的令牌负载",
            )
        return UUID(user_id)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e


async def get_current_user(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
):
    """从数据库中获取当前用户。"""
    user_repo = TortoiseUserRepository()
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )
    return user


async def get_superuser(
    user=Depends(get_current_user),
):
    """确保当前用户是超级用户。"""
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超级用户权限",
        )
    return user


# 仓库依赖项
def get_user_repository() -> TortoiseUserRepository:
    return TortoiseUserRepository()


def get_novel_repository():
    from novelvids.infrastructure.database.repositories import TortoiseNovelRepository
    return TortoiseNovelRepository()


def get_chapter_repository():
    from novelvids.infrastructure.database.repositories import TortoiseChapterRepository
    return TortoiseChapterRepository()



def get_scene_repository():
    from novelvids.infrastructure.database.repositories import TortoiseSceneRepository
    return TortoiseSceneRepository()


def get_video_repository():
    from novelvids.infrastructure.database.repositories import TortoiseVideoRepository
    return TortoiseVideoRepository()


def get_usage_repository():
    from novelvids.infrastructure.database.repositories import TortoiseUsageRecordRepository
    return TortoiseUsageRecordRepository()


def get_workflow_repository():
    from novelvids.infrastructure.database.repositories import TortoiseWorkflowRepository
    return TortoiseWorkflowRepository()
