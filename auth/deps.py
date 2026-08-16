"""鉴权依赖：当前用户、角色守卫、团队访问校验。

开关语义：`AUTH_ENABLED=false` 时所有依赖退化为 no-op（匿名放行），
行为与无鉴权版本完全一致；`true` 时执行严格鉴权与角色检查。
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request

from auth.models import TeamMember, User, UserSession
from auth.security import hash_token
from config import settings
from models.ai_task import AiTask
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from utils.enums import UserStatusEnum


@dataclass
class AuthContext:
    """鉴权上下文：当前用户、团队成员身份与超管标记。"""

    user: Optional[User] = None
    membership: Optional[TeamMember] = None
    team_id: Optional[int] = None
    is_super_admin: bool = False

    @property
    def is_anonymous(self) -> bool:
        return self.user is None


def auth_disabled() -> bool:
    return not settings.AUTH_ENABLED


def extract_bearer_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <token> 提取令牌；缺失返回 None。"""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


async def get_current_user(request: Request) -> Optional[User]:
    """解析当前登录用户。开关关闭时返回 None（匿名模式）。"""
    if auth_disabled():
        return None
    token = extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    session = await UserSession.get_or_none(
        token_hash=hash_token(token)
    ).select_related("user")
    now = datetime.now(timezone.utc)
    if session is None or session.expires_at <= now:
        if session is not None:
            await session.delete()
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if session.user.status != UserStatusEnum.active.value:
        raise HTTPException(status_code=403, detail="账号已停用")
    session.last_seen_at = now
    await session.save(update_fields=["last_seen_at", "updated_at"])
    return session.user


async def get_auth_context(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> AuthContext:
    """组装鉴权上下文。超管跨团队；普通用户按侧边栏选中的团队（X-Team-Id）
    解析成员身份，未指定时回退到第一个可用团队成员。"""
    if auth_disabled() or user is None:
        return AuthContext()
    if user.is_super_admin:
        return AuthContext(user=user, is_super_admin=True)
    selected_team_id = _selected_team_id(request)
    query = TeamMember.filter(user=user, team__status=1, status=1)
    if selected_team_id is not None:
        membership = await (
            query.filter(team_id=selected_team_id).select_related("team").first()
        )
    else:
        membership = await query.select_related("team").first()
    if membership is None:
        raise HTTPException(status_code=403, detail="没有加入任何可用团队")
    return AuthContext(
        user=user,
        membership=membership,
        team_id=membership.team_id,
        is_super_admin=False,
    )


def _selected_team_id(request: Request) -> Optional[int]:
    """解析 X-Team-Id 请求头（侧边栏团队选择器写入）。"""
    raw = request.headers.get("X-Team-Id", "")
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def require_roles(*roles: str):
    """角色守卫依赖工厂：超管放行；普通成员必须命中 roles 之一，否则 403。"""

    async def dependency(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth_disabled() or ctx.user is None or ctx.is_super_admin:
            return ctx
        if ctx.membership is None or ctx.membership.role not in roles:
            raise HTTPException(status_code=403, detail="没有权限执行此操作")
        return ctx

    return dependency


async def require_super_admin(
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """超管守卫：仅平台超级管理员可访问。"""
    if auth_disabled():
        return ctx
    if not ctx.is_super_admin:
        raise HTTPException(status_code=403, detail="仅超级管理员可执行此操作")
    return ctx


async def require_team_access(
    novel_id: int,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """校验当前用户可访问指定项目。

    开关关闭 / 超管：放行。
    普通成员：novel 必须存在且 team_id 等于其所在团队，否则一律 404
    （不泄露其他团队项目的存在性）。
    """
    await ensure_novel_access(novel_id, ctx)
    return ctx


async def ensure_novel_access(novel_id: int, ctx: AuthContext) -> None:
    """团队访问校验（函数形式，供路由在解析 body 后手动调用）。"""
    if auth_disabled() or ctx.user is None or ctx.is_super_admin:
        return
    novel = await Novel.get_or_none(id=novel_id)
    if novel is None or novel.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail="项目不存在")


async def require_chapter_access(
    chapter_id: int,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """章节访问校验：通过章节归属项目校验团队。"""
    chapter = await Chapter.get_or_none(id=chapter_id).select_related("novel")
    if chapter is not None:
        await ensure_novel_access(chapter.novel_id, ctx)
    elif not auth_disabled() and ctx.user is not None and not ctx.is_super_admin:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ctx


async def require_scene_access(
    scene_id: int,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """分镜访问校验：通过分镜归属章节再归属项目校验团队。"""
    scene = await Scene.get_or_none(id=scene_id).select_related(
        "chapter__novel"
    )
    if scene is not None:
        await ensure_novel_access(scene.chapter.novel_id, ctx)
    elif not auth_disabled() and ctx.user is not None and not ctx.is_super_admin:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return ctx


async def require_video_access(
    video_id: int,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """视频访问校验：通过视频→分镜→章节→项目校验团队。"""
    video = await Video.get_or_none(id=video_id).select_related(
        "scene__chapter__novel"
    )
    if video is not None:
        await ensure_novel_access(video.scene.chapter.novel_id, ctx)
    elif not auth_disabled() and ctx.user is not None and not ctx.is_super_admin:
        raise HTTPException(status_code=404, detail="视频不存在")
    return ctx


async def require_asset_access(
    asset_id: int,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """资产访问校验：通过资产归属项目校验团队。"""
    asset = await Asset.get_or_none(id=asset_id).select_related("novel")
    if asset is not None:
        await ensure_novel_access(asset.novel_id, ctx)
    elif not auth_disabled() and ctx.user is not None and not ctx.is_super_admin:
        raise HTTPException(status_code=404, detail="资产不存在")
    return ctx


async def require_task_access(
    task_id,
    ctx: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """AI 任务访问校验：从任务参数解析归属项目并校验团队。"""
    task = await AiTask.get_or_none(id=task_id)
    if task is None:
        if not auth_disabled() and ctx.user is not None and not ctx.is_super_admin:
            raise HTTPException(status_code=404, detail="任务不存在")
        return ctx
    params = task.request_params or {}
    novel_id = params.get("novel_id")
    if novel_id is None and params.get("chapter_id"):
        chapter = await Chapter.get_or_none(id=params["chapter_id"])
        novel_id = chapter.novel_id if chapter else None
    if novel_id is not None:
        await ensure_novel_access(novel_id, ctx)
    return ctx
