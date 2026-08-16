"""登录方式 Provider 抽象接口。

一期实现：`auth.service.PasswordAuthService`（账号密码）。
二期实现：微信公众平台扫码关注登录（`WeChatMpProvider`），
接入时实现本接口并在 auth 路由中按配置暴露对应入口，不动现有登录契约。
"""

import abc


class AuthProvider(abc.ABC):
    """登录提供方接口。每个实现负责一种登录方式。"""

    name: str = ""

    @abc.abstractmethod
    async def authenticate(self, payload: dict) -> "auth.models.User | None":
        """凭 payload 完成认证；成功返回用户，失败返回 None 或抛 401。"""
