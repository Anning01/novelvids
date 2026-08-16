"""账单计费控制器。"""

from services.billing import aggregation


class BillingController:
    async def summary(self, novel_id: int | None = None) -> dict:
        return await aggregation.summary(novel_id)

    async def projects(self, page: int, page_size: int) -> dict:
        return await aggregation.project_costs(page, page_size)

    async def project_detail(self, novel_id: int) -> dict:
        return await aggregation.project_detail(novel_id)

    async def records(self, params) -> dict:
        return await aggregation.list_records(params)


billing_controller = BillingController()
