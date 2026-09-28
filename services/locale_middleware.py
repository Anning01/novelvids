"""Resolve the shared display language once per API request."""

from tortoise.exceptions import ConfigurationError, OperationalError
from services.language import configured_language
from utils.messages import message_language


class LocaleMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        try:
            language = await configured_language()
        except (ConfigurationError, OperationalError):
            # Error rendering must remain available if the database is down.
            language = "en"
        token = message_language.set(language)
        try:
            await self.app(scope, receive, send)
        finally:
            message_language.reset(token)
