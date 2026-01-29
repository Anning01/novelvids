"""V1 API router."""

from fastapi import APIRouter

from novelvids.api.v1.endpoints import (
    assets_router,
    auth_router,
    chapters_router,
    dashboard_router,
    extraction_router,
    generation_router,
    novels_router,
    storyboard_router,
)

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
router.include_router(novels_router)
router.include_router(chapters_router)
router.include_router(assets_router)
router.include_router(dashboard_router)
router.include_router(generation_router)
router.include_router(extraction_router)
router.include_router(storyboard_router)
