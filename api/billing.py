
from utils.messages import localized_message
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from auth.deps import AuthContext, require_roles, require_project_audit_access, require_super_admin
from controllers.billing import billing_controller, billing_scope
from schemas.billing import (
    BillingProjectDetailOut,
    BillingProjectOut,
    BillingSummaryOut,
    ModelUsageRecordOut,
    StatementFilters,
    StatementOut,
    StatementPartiesOut,
    StatementQuery,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

# 成本可见性：管理员=全团队；创作者=仅本人；查看者 403
_BILLING = Depends(require_roles("admin", "creator"))


async def statement_admin(ctx: AuthContext = Depends(require_super_admin)) -> AuthContext:
    # Anonymous access has no team ledger; never expose this administrative view there.
    if not ctx.is_super_admin:
        raise HTTPException(403, localized_message('仅超级管理员可执行此操作'))
    return ctx


@router.get('/statements/parties', response_model=ResponseSchema[StatementPartiesOut], summary='消费账单团队与用户')
async def statement_parties(response: Response, ctx: AuthContext = Depends(statement_admin)):
    response.headers['Cache-Control'] = 'no-store'
    return ResponseSchema(data=await billing_controller.statements.parties())


@router.get('/statements', response_model=ResponseSchema[StatementOut], summary='实际消费账单（仅超级管理员）')
async def statements(response: Response, filters: Annotated[StatementQuery, Query()], ctx: AuthContext = Depends(statement_admin)):
    response.headers['Cache-Control'] = 'no-store'
    return ResponseSchema(data=await billing_controller.statements.list(filters, filters.page, filters.page_size))


@router.get('/statements/export', summary='导出全部匹配的实际消费账单（仅超级管理员）')
async def export_statements(filters: Annotated[StatementFilters, Query()], ctx: AuthContext = Depends(statement_admin)):
    return StreamingResponse(billing_controller.statements.export(filters), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': 'attachment; filename="billing-statement.csv"',
                                      'Cache-Control': 'no-store'})


@router.get("/summary", summary="账单汇总", response_model=ResponseSchema[BillingSummaryOut])
async def get_billing_summary(
    novel_id: int | None = None,
    ctx: AuthContext = _BILLING,
):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(
        data=await billing_controller.summary(novel_id, team_id, user_id)
    )


@router.get(
    "/projects",
    summary="项目成本列表",
    response_model=ResponseSchema[PaginationResponse[BillingProjectOut]],
)
async def get_billing_projects(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = _BILLING,
):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(
        data=await billing_controller.projects(
            params.page, params.page_size, team_id, user_id
        )
    )


@router.get(
    "/projects/{novel_id}",
    summary="单项目成本明细",
    response_model=ResponseSchema[BillingProjectDetailOut],
)
async def get_billing_project_detail(
    novel_id: int,
    ctx: AuthContext = _BILLING,
    _: AuthContext = Depends(require_project_audit_access),
):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(
        data=await billing_controller.project_detail(novel_id, team_id, user_id)
    )


@router.get(
    "/records",
    summary="计费流水列表",
    response_model=ResponseSchema[PaginationResponse[ModelUsageRecordOut]],
)
async def get_billing_records(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = _BILLING,
):
    team_id, user_id = billing_scope(ctx)
    return ResponseSchema(
        data=await billing_controller.records(params, team_id, user_id)
    )


@router.get('/records/{record_id}/details', summary='流水原始明细',
            response_model=ResponseSchema[PaginationResponse[ModelUsageRecordOut]])
async def get_billing_record_details(record_id: int, params: QueryParams = Depends(get_list_params), ctx: AuthContext = _BILLING):
    team_id, user_id = billing_scope(ctx)
    try:
        return ResponseSchema(data=await billing_controller.records(params, team_id, user_id, record_id))
    except LookupError:
        raise HTTPException(404, localized_message('当前范围内不存在该流水')) from None
