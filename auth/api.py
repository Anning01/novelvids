"""鉴权 API：状态探测 / 登录 / 当前用户 / 登出。

`public_router`（/status）在两种模式下都注册，供前端判断开关状态；
其余路由仅在 AUTH_ENABLED=true 时由 main.py 注册。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auth import qiling
from auth.deps import extract_bearer_token, get_current_user
from auth.schemas import ChangePasswordIn, LoginIn, LoginOut, MeOut, ProfileUpdateIn, RegisterIn, UserOut
from auth.service import auth_service
from config import settings
from services.security.login_throttle import login_throttle
from utils.response_format import ResponseSchema
from services.legal_documents import profile_status, render
from typing import Literal

public_router = APIRouter()

router = APIRouter()


@public_router.get("/status", summary="登录功能状态探测", response_model=ResponseSchema[dict])
async def auth_status():
    legal, missing = profile_status()
    return ResponseSchema(data={"enabled": settings.AUTH_ENABLED, "provider": settings.AUTH_PROVIDER,
                                "qiling_enabled": qiling.enabled(), "legal_ready": legal is not None,
                                "legal_missing": missing})


@public_router.get("/legal/{kind}", response_class=HTMLResponse)
async def legal_document(kind: Literal["terms", "privacy"]):
    return HTMLResponse(render(kind), headers={"Cache-Control": "no-store"})


def password_provider():
    if settings.AUTH_PROVIDER != "password":
        raise HTTPException(404, "账号密码登录未启用")


@router.post("/login", response_model=ResponseSchema[LoginOut], dependencies=[Depends(password_provider)])
async def password_login(data: LoginIn, request: Request):
    attempt = await login_throttle.before_attempt(request, data.username)
    try:
        result = await auth_service.login(data)
    except HTTPException:
        await login_throttle.record_failure(attempt)
        raise
    await login_throttle.record_success(attempt)
    return ResponseSchema(data=result)


@router.post("/register", response_model=ResponseSchema[LoginOut], dependencies=[Depends(password_provider)])
async def password_register(data: RegisterIn, request: Request):
    await login_throttle.before_attempt(request, data.username)
    return ResponseSchema(data=await auth_service.register(data))


@router.post("/change-password", dependencies=[Depends(password_provider)])
async def password_change(data: ChangePasswordIn, user=Depends(get_current_user)):
    await auth_service.change_password(user, data.old_password, data.new_password)
    return ResponseSchema(data=None, message="密码已修改")


class QilingPollIn(BaseModel):
    attempt: str = Field(min_length=32, max_length=64)


@router.post("/qiling/start")
async def qiling_start(request: Request):
    await login_throttle.before_attempt(request, "qiling-start")
    return ResponseSchema(data=await qiling.start())


@router.post("/qiling/poll")
async def qiling_poll(data: QilingPollIn, request: Request):
    await login_throttle.before_attempt(request, "qiling-poll")
    return ResponseSchema(data=await qiling.poll(data.attempt))


@router.post("/qiling/bind/start")
async def qiling_bind_start(request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "qiling-bind-start")
    return ResponseSchema(data=await qiling.start(user))


@router.post("/qiling/bind/poll")
async def qiling_bind_poll(data: QilingPollIn, request: Request, user=Depends(get_current_user)):
    await login_throttle.before_attempt(request, "qiling-bind-poll")
    return ResponseSchema(data=await qiling.poll(data.attempt, user))


@router.get("/me", summary="当前用户信息", response_model=ResponseSchema[MeOut])
async def me(user=Depends(get_current_user)):
    return ResponseSchema(data=await auth_service.me(user))


@router.patch('/profile', summary='修改本人的昵称', response_model=ResponseSchema[UserOut])
async def update_profile(data: ProfileUpdateIn, user=Depends(get_current_user)):
    from services.user_profile import update_nickname
    return ResponseSchema(data=await update_nickname(user, data.nickname))


@router.post('/avatar', summary='上传本人的头像', response_model=ResponseSchema[UserOut])
async def upload_avatar(file: UploadFile = File(...), user=Depends(get_current_user)):
    from services.user_profile import update_avatar
    return ResponseSchema(data=await update_avatar(user, file))


@router.post("/logout", summary="退出登录", response_model=ResponseSchema[None])
async def logout(request: Request):
    await auth_service.logout(extract_bearer_token(request))
    return ResponseSchema(data=None, message="已退出登录")
