"""账单聚合：总览、项目成本、项目明细、流水分页。"""

from collections import defaultdict
from decimal import Decimal

from models.novel import Novel
from models.usage_record import ModelUsageRecord
from schemas.billing import ModelUsageRecordOut
from utils.page import QueryBuilder


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _money(value: Decimal) -> float:
    return round(float(value), 6)


async def summary(
    novel_id: int | None = None,
    team_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if novel_id is not None:
        query = query.filter(novel_id=novel_id)
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    rows = await query.values(
        "task_type", "billing_type", "model", "model_name", "cost", "created_at"
    )
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_billing: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    by_model: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    daily: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        cost = _dec(row["cost"])
        by_billing[row["billing_type"]] += cost
        by_task[row["task_type"]] += cost
        by_model[row["model_name"] or row["model"] or "未知模型"] += cost
        daily[row["created_at"].date().isoformat()] += cost
    return {
        "total_cost": _money(total),
        "total_records": len(rows),
        "by_billing_type": [
            {"billing_type": key, "cost": _money(value)}
            for key, value in sorted(by_billing.items())
        ],
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
        "by_model": [
            {"model": key, "cost": _money(value)}
            for key, value in sorted(by_model.items(), key=lambda item: -item[1])
        ],
        "daily_trend": [
            {"date": key, "cost": _money(value)}
            for key, value in sorted(daily.items())
        ],
    }


async def project_costs(
    page: int,
    page_size: int,
    team_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    rows = await query.values("novel_id", "cost")
    agg: dict[int, dict] = defaultdict(
        lambda: {"total_cost": Decimal("0"), "record_count": 0}
    )
    for row in rows:
        novel_id = row["novel_id"]
        agg[novel_id]["total_cost"] += _dec(row["cost"])
        agg[novel_id]["record_count"] += 1
    novel_ids = list(agg.keys())
    novels = (
        {novel.id: novel.name for novel in await Novel.filter(id__in=novel_ids)}
        if novel_ids
        else {}
    )
    items = [
        {
            "novel_id": novel_id,
            "novel_name": novels.get(novel_id, "（已删除项目）"),
            "total_cost": _money(value["total_cost"]),
            "record_count": value["record_count"],
        }
        for novel_id, value in sorted(
            agg.items(), key=lambda item: -item[1]["total_cost"]
        )
    ]
    total = len(items)
    pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
    }


async def project_detail(
    novel_id: int,
    team_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    novel = await Novel.get_or_none(id=novel_id)
    query = ModelUsageRecord.filter(novel_id=novel_id)
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    rows = await query.values("task_type", "cost")
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        by_task[row["task_type"]] += _dec(row["cost"])
    return {
        "novel_id": novel_id,
        "novel_name": novel.name if novel else "（已删除项目）",
        "total_cost": _money(total),
        "record_count": len(rows),
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
    }


async def list_records(
    params,
    team_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    query = await QueryBuilder.apply_filters(query, ModelUsageRecord, params.filters or {})
    query = query.order_by("-id")
    total = await query.count()
    query = await QueryBuilder.apply_pagination(query, params.page, params.page_size)
    items = await query
    items_out = [ModelUsageRecordOut.model_validate(item) for item in items]
    pages = (total + params.page_size - 1) // params.page_size if total else 0
    return {
        "items": items_out,
        "pagination": {
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
            "pages": pages,
        },
    }
