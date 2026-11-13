from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from api.config import require_studio_owner
from services.releases import LOCAL, version_key
from services.releases.status import latest_release, updater
from utils.response_format import ResponseSchema

router = APIRouter()


async def tasks_active():
    from models.ai_task import AiTask
    from utils.enums import TaskStatusEnum
    return await AiTask.filter(status__in=[TaskStatusEnum.pending, TaskStatusEnum.running, TaskStatusEnum.queued]).exists()


@router.get("/installed")
async def installed(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data={"version": LOCAL["version"], "busy": await tasks_active()})


@router.get("")
async def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data={"installed": LOCAL["version"], "latest": await latest_release(), "updater": await updater()})


class UpdateRequest(BaseModel):
    version: str = Field(pattern=r"^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$")


@router.post("", dependencies=[Depends(require_studio_owner)])
async def update(body: UpdateRequest):
    latest = await latest_release()
    if not latest or not latest["online"] or latest["version"] != body.version or version_key(body.version) <= version_key(LOCAL["version"]):
        raise HTTPException(409, "请刷新版本信息后重试")
    if await tasks_active():
        raise HTTPException(409, "有任务正在进行，请在任务结束后升级")
    return ResponseSchema(data=await updater("POST", body.version))
