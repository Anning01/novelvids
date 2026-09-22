"""HTTP boundary for shared transactional workbench object operations."""

from contextlib import asynccontextmanager

from fastapi import HTTPException

from services.creation_objects import project_write


@asynccontextmanager
async def creation_write(novel_id: int):
    try:
        async with project_write(novel_id) as connection:
            yield connection
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
