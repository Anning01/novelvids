"""账单计费控制器。"""

from auth.deps import AuthContext
from services.billing import aggregation
from services.billing.statements import billing_statements


def billing_scope(ctx: AuthContext) -> tuple[int | None, int | None]:
    """返回 (team_id, user_id) 过滤条件：超管看全部，创作者只看自己。"""
    if ctx.is_super_admin:
        return None, None
    if ctx.membership and ctx.membership.role == "creator":
        return ctx.team_id, ctx.user.id
    return ctx.team_id, None


class BillingController:
    statements = billing_statements

    async def summary(
        self,
        novel_id: int | None = None,
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> dict:
        return await aggregation.summary(novel_id, team_id, user_id)

    async def projects(
        self,
        page: int,
        page_size: int,
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> dict:
        return await aggregation.project_costs(page, page_size, team_id, user_id)

    async def project_detail(
        self,
        novel_id: int,
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> dict:
        return await aggregation.project_detail(novel_id, team_id, user_id)

    async def records(
        self,
        params,
        team_id: int | None = None,
        user_id: int | None = None,
        record_id: int | None = None,
    ) -> dict:
        return await aggregation.list_records(params, team_id, user_id, record_id)


billing_controller = BillingController()
