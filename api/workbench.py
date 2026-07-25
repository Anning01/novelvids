from fastapi import APIRouter

from schemas.workbench import WorkbenchCapabilitiesOut
from utils.response_format import ResponseSchema

router = APIRouter()


@router.get(
    "/capabilities",
    summary="获取创作画布能力",
    response_model=ResponseSchema[WorkbenchCapabilitiesOut],
)
async def get_workbench_capabilities():
    return ResponseSchema(data=WorkbenchCapabilitiesOut())
