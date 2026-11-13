"""Exchange a one-time Qiling WeChat login for a NovelVids session."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from auth.models import QilingIdentity, QilingLoginAttempt, TeamMember, User
from auth.security import hash_token, new_session_token
from auth.service import auth_service
from config import settings
from services.team_provisioning import create_owned_team
from utils.messages import localized_message as msg


class UpstreamAttempt(BaseModel):
    state: str = Field(min_length=1, max_length=200)
    auth_url: str
    expires_in: int = Field(gt=0, le=600)


class UpstreamIdentity(BaseModel):
    sub: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=120)


def enabled() -> bool:
    return bool(_platform_login() and settings.QILING_API_BASE_URL)


def _platform_login() -> bool:
    return settings.AUTH_ENABLED and settings.DEPLOYMENT_ROLE == "platform" and settings.AUTH_PROVIDER == "qiling"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _request(method: str, path: str, **kwargs) -> dict:
    if not enabled():
        raise HTTPException(503, msg("器灵登录尚未配置"))
    base = urlsplit(settings.QILING_API_BASE_URL)
    if (base.scheme != "https" or not base.hostname or base.username or base.password or base.query
            or base.fragment or base.path or len(settings.QILING_API_BASE_URL) > 255):
        raise HTTPException(503, msg("器灵登录尚未配置"))
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.request(method, settings.QILING_API_BASE_URL + path, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
    except (httpx.HTTPError, ValueError):
        pass
    raise HTTPException(502, msg("器灵暂不可用，请重试"))


async def start(user: User | None = None) -> dict:
    if not _platform_login():
        raise HTTPException(404, msg("登录方式不可用"))
    if user and await QilingIdentity.filter(user_id=user.id).exists():
        raise HTTPException(409, msg("当前账号已绑定器灵"))
    payload = await _request("POST", "/api/v1/auth/wechat/session", json={"redirect_path": "/"})
    try:
        upstream = UpstreamAttempt.model_validate(payload)
        authorize = urlsplit(upstream.auth_url)
        if authorize.scheme != "https" or not authorize.hostname or authorize.username or authorize.password:
            raise ValueError
    except (ValidationError, ValueError):
        raise HTTPException(502, msg("器灵返回了无效的登录信息")) from None
    token = new_session_token()
    now = _now()
    await QilingLoginAttempt.filter(expires_at__lte=now).delete()
    await QilingLoginAttempt.create(token_hash=hash_token(token), upstream_state=upstream.state,
                                    issuer=settings.QILING_API_BASE_URL, binding_user=user,
                                    expires_at=now + timedelta(seconds=upstream.expires_in))
    return {"attempt": token, "authorization_url": upstream.auth_url, "expires_in": upstream.expires_in}


async def poll(token: str, user: User | None = None) -> dict:
    if not _platform_login():
        raise HTTPException(404, msg("登录方式不可用"))
    key = hash_token(token)
    owner_id = user.id if user else None
    attempt = await QilingLoginAttempt.get_or_none(token_hash=key, binding_user_id=owner_id)
    if not attempt or attempt.expires_at <= _now() or attempt.issuer != settings.QILING_API_BASE_URL:
        return {"status": "expired"}
    result = await _request("GET", "/api/v1/auth/wechat/status/" + quote(attempt.upstream_state, safe=""))
    status = result.get("status")
    if status == "pending":
        return {"status": "pending"}
    if status != "completed":
        return {"status": "expired" if status in ("expired", "consumed") else "failed"}
    upstream_token = result.get("access_token")
    if not isinstance(upstream_token, str) or not upstream_token:
        raise HTTPException(502, msg("器灵返回了无效的登录信息"))
    try:
        identity = UpstreamIdentity.model_validate(await _request(
            "GET", "/api/v1/auth/me", headers={"Authorization": f"Bearer {upstream_token}"},
        ))
    except ValidationError:
        raise HTTPException(502, msg("器灵返回了无效的登录信息")) from None
    try:
        async with in_transaction():
            consumed = await QilingLoginAttempt.filter(token_hash=key, binding_user_id=owner_id,
                                                       expires_at__gt=_now()).delete()
            if not consumed:
                return {"status": "expired"}
            linked = await QilingIdentity.get_or_none(issuer=attempt.issuer, subject=identity.sub).select_related("user")
            if user:
                if linked or await QilingIdentity.filter(user_id=user.id).exists():
                    raise HTTPException(409, msg("该器灵账号或猫影账号已绑定"))
                await QilingIdentity.create(issuer=attempt.issuer, subject=identity.sub, user=user)
                return {"status": "bound"}
            if linked:
                target = linked.user
            else:
                if not settings.QILING_SIGNUP_ENABLED:
                    raise HTTPException(403, msg("暂未开放器灵注册，请先登录并绑定器灵账号"))
                from services.legal_documents import require_profile
                require_profile()
                target = await User.create(username=f"qiling-{uuid4().hex}", nickname=identity.name[:100])
                await QilingIdentity.create(issuer=attempt.issuer, subject=identity.sub, user=target)
                await create_owned_team(target.id)
            if target.status != 1:
                raise HTTPException(403, msg("账号已停用"))
            if linked and not target.is_super_admin and target.password_hash == "!" and target.username.startswith("qiling-"):
                if not await TeamMember.filter(user_id=target.id).exists():
                    await create_owned_team(target.id)
            return {"status": "completed", "session": await auth_service.issue_session(target)}
    except IntegrityError:
        raise HTTPException(409, msg("账号已绑定，请重新发起登录")) from None
