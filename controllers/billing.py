"""账单计费控制器。"""

from services.billing import aggregation


class BillingController:
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
    ) -> dict:
        return await aggregation.list_records(params, team_id, user_id)


billing_controller = BillingController()
