from fastapi import APIRouter, Depends

from controllers.billing import billing_controller
from schemas.billing import (
    BillingProjectDetailOut,
    BillingProjectOut,
    BillingSummaryOut,
    ModelUsageRecordOut,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.get("/summary", summary="账单汇总", response_model=ResponseSchema[BillingSummaryOut])
async def get_billing_summary(novel_id: int | None = None):
    return ResponseSchema(data=await billing_controller.summary(novel_id))


@router.get(
    "/projects",
    summary="项目成本列表",
    response_model=ResponseSchema[PaginationResponse[BillingProjectOut]],
)
async def get_billing_projects(params: QueryParams = Depends(get_list_params)):
    return ResponseSchema(data=await billing_controller.projects(params.page, params.page_size))


@router.get(
    "/projects/{novel_id}",
    summary="单项目成本明细",
    response_model=ResponseSchema[BillingProjectDetailOut],
)
async def get_billing_project_detail(novel_id: int):
    return ResponseSchema(data=await billing_controller.project_detail(novel_id))


@router.get(
    "/records",
    summary="计费流水列表",
    response_model=ResponseSchema[PaginationResponse[ModelUsageRecordOut]],
)
async def get_billing_records(params: QueryParams = Depends(get_list_params)):
    return ResponseSchema(data=await billing_controller.records(params))
