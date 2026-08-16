"""鉴权 API：状态探测 / 登录 / 当前用户 / 登出 / 修改密码。

`public_router`（/status）在两种模式下都注册，供前端判断开关状态；
其余路由仅在 AUTH_ENABLED=true 时由 main.py 注册。
"""

from fastapi import APIRouter, Depends, Request

from auth.deps import extract_bearer_token, get_current_user
from auth.schemas import ChangePasswordIn, LoginIn, LoginOut, MeOut, RegisterIn
from auth.service import auth_service
from config import settings
from utils.response_format import ResponseSchema

public_router = APIRouter()

router = APIRouter()


@public_router.get("/status", summary="登录功能状态探测", response_model=ResponseSchema[dict])
async def auth_status():
    return ResponseSchema(data={"enabled": settings.AUTH_ENABLED})


@router.post("/register", summary="经邀请链接注册", response_model=ResponseSchema[LoginOut])
async def register(data: RegisterIn):
    return ResponseSchema(data=await auth_service.register(data))


@router.post("/login", summary="账号密码登录", response_model=ResponseSchema[LoginOut])
async def login(data: LoginIn):
    return ResponseSchema(data=await auth_service.login(data))


@router.get("/me", summary="当前用户信息", response_model=ResponseSchema[MeOut])
async def me(user=Depends(get_current_user)):
    return ResponseSchema(data=await auth_service.me(user))


@router.post("/logout", summary="退出登录", response_model=ResponseSchema[None])
async def logout(request: Request):
    await auth_service.logout(extract_bearer_token(request))
    return ResponseSchema(data=None, message="已退出登录")


@router.post(
    "/change-password", summary="修改密码", response_model=ResponseSchema[None]
)
async def change_password(data: ChangePasswordIn, user=Depends(get_current_user)):
    await auth_service.change_password(user, data.old_password, data.new_password)
    return ResponseSchema(data=None, message="密码已修改")
