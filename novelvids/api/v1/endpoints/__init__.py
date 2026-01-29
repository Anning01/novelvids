"""V1 API endpoints."""

from novelvids.api.v1.endpoints.assets import router as assets_router
from novelvids.api.v1.endpoints.auth import router as auth_router
from novelvids.api.v1.endpoints.chapters import router as chapters_router
from novelvids.api.v1.endpoints.dashboard import router as dashboard_router
from novelvids.api.v1.endpoints.extraction import router as extraction_router
from novelvids.api.v1.endpoints.generation import router as generation_router
from novelvids.api.v1.endpoints.novels import router as novels_router
from novelvids.api.v1.endpoints.storyboard import router as storyboard_router


__all__ = [
    "assets_router",
    "auth_router",
    "novels_router",
    "chapters_router",
    "extraction_router",
    "generation_router",
    "dashboard_router",
    "storyboard_router",
]
