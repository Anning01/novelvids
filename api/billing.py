from fastapi import APIRouter, Depends

from auth.deps import AuthContext, require_roles, require_team_access
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

# 成本可见性：管理员=全团队；创作者=仅本人；查看者 403
_BILLING = Depends(require_roles("admin", "creator"))


def _team_scope(ctx: AuthContext) -> tuple[int | None, int | None]:
    """返回 (team_id, user_id) 过滤条件：超管看全部，创作者只看自己。"""
    if ctx.is_super_admin:
        return None, None
    if ctx.membership and ctx.membership.role == "creator":
        return ctx.team_id, ctx.user.id
    return ctx.team_id, None


@router.get("/summary", summary="账单汇总", response_model=ResponseSchema[BillingSummaryOut])
async def get_billing_summary(
    novel_id: int | None = None,
    ctx: AuthContext = _BILLING,
):
    team_id, user_id = _team_scope(ctx)
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
    team_id, user_id = _team_scope(ctx)
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
    _: AuthContext = Depends(require_team_access),
):
    team_id, user_id = _team_scope(ctx)
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
    team_id, user_id = _team_scope(ctx)
    return ResponseSchema(
        data=await billing_controller.records(params, team_id, user_id)
    )
