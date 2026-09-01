"""不干扰流式响应的纯 ASGI 安全响应头中间件。"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app,
        *,
        content_security_policy: str,
        docs_content_security_policy: str,
    ):
        self.app = app
        self.content_security_policy = content_security_policy
        self.docs_content_security_policy = docs_content_security_policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = (
                    "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
                )
                headers["Cross-Origin-Opener-Policy"] = "same-origin"
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = self._policy_for(path)
                status = int(message.get("status", 0))
                if (
                    status in {200, 206}
                    and path.startswith("/media/")
                    and "/derivatives/" in path
                ):
                    headers["Cache-Control"] = (
                        "public, max-age=31536000, immutable"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _policy_for(self, path: str) -> str:
        if path == "/docs" or path.startswith("/docs/") or path == "/redoc":
            return self.docs_content_security_policy
        return self.content_security_policy
