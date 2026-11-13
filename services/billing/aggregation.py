"""账单聚合：总览、项目成本、项目明细、流水分页。"""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from config import settings
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.billing.record_view import BillingRecordView
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
    *, cost_source: str | None = None, recent_days: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if cost_source is not None:
        query = query.filter(cost_source=cost_source)
    if novel_id is not None:
        query = query.filter(novel_id=novel_id)
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    days = []
    if recent_days is not None:
        end = datetime.now(settings.tz).date() + timedelta(days=1)
        start = end - timedelta(days=recent_days)
        query = query.filter(
            created_at__gte=datetime.combine(start, time.min, settings.tz).astimezone(timezone.utc),
            created_at__lt=datetime.combine(end, time.min, settings.tz).astimezone(timezone.utc),
        )
        days = [(start + timedelta(days=offset)).isoformat() for offset in range(recent_days)]
    rows = await query.values(
        "task_type", "billing_type", "model", "model_name", "cost", "created_at", "platform_cost", "local_charge", "settlement_status"
    )
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_billing: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    by_model: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    model_records: Counter[str] = Counter()
    daily: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        cost = _dec(row["cost"])
        by_billing[row["billing_type"]] += cost
        by_task[row["task_type"]] += cost
        model = row["model_name"] or row["model"] or "未知模型"
        by_model[model] += cost
        model_records[model] += 1
        created_at = row["created_at"]
        if recent_days is not None:
            created_at = created_at.astimezone(settings.tz)
        daily[created_at.date().isoformat()] += cost
    return {
        "total_cost": _money(total),
        "total_records": len(rows),
        "platform_cost": _money(sum((_dec(row["platform_cost"]) for row in rows), Decimal("0"))),
        "local_charge": _money(sum((_dec(row["local_charge"]) for row in rows), Decimal("0"))),
        "pending_records": sum(row["settlement_status"] in {"pending", "review"} for row in rows),
        "by_billing_type": [
            {"billing_type": key, "cost": _money(value)}
            for key, value in sorted(by_billing.items())
        ],
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
        "by_model": [
            {"model": key, "cost": _money(value), "record_count": model_records[key]}
            for key, value in sorted(by_model.items(), key=lambda item: -item[1])
        ],
        "daily_trend": [
            {"date": day, "cost": _money(daily[day])}
            for day in (days or sorted(daily))
        ],
    }


async def _project_usage_totals(
    team_id: int | None = None,
    user_id: int | None = None,
    project_ids: list[int] | None = None,
) -> dict[int, dict]:
    if project_ids == []:
        return {}
    query = ModelUsageRecord.exclude(novel_id=0)
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    if project_ids is not None:
        query = query.filter(novel_id__in=project_ids)
    rows = await query.values("novel_id", "cost", "settlement_status")
    agg: dict[int, dict] = defaultdict(
        lambda: {"total_cost": Decimal("0"), "record_count": 0, "pending_records": 0}
    )
    for row in rows:
        novel_id = row["novel_id"]
        agg[novel_id]["total_cost"] += _dec(row["cost"])
        agg[novel_id]["record_count"] += 1
        agg[novel_id]["pending_records"] += int(row["settlement_status"] in {"pending", "review"})
    return agg


async def recorded_project_costs(project_ids: list[int], team_id: int | None, user_id: int | None) -> dict[int, dict]:
    totals = await _project_usage_totals(team_id, user_id, project_ids)
    return {project_id: {**value, "total_cost": _money(value["total_cost"])} for project_id, value in totals.items()}


async def project_costs(
    page: int,
    page_size: int,
    team_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    agg = await _project_usage_totals(team_id, user_id)
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
            "pending_records": value["pending_records"],
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
    record_id: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    query = await QueryBuilder.apply_filters(query, ModelUsageRecord, params.filters or {})
    view = BillingRecordView(query)
    return await view.details(record_id, params) if record_id is not None else await view.list(params)
