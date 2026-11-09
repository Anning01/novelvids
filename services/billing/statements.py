"""Read actual balance deductions without changing billing or exposing model configuration."""

import csv
import io
from datetime import datetime, time, timedelta
from decimal import Decimal

from tortoise.functions import Count, Sum
from tortoise.expressions import Subquery

from auth.models import BalanceTransaction, Team, User
from config import settings
from models.ai_task import AiTask
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from models.video import Video
from schemas.billing import StatementFilters, StatementRowOut
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.messages import localized_message


SAFE_USAGE_FIELDS = ('input_tokens', 'output_tokens', 'image_count', 'input_image_count',
                     'seconds', 'resolution', 'clarity', 'fps', 'duration_seconds', 'missing_usage')
EXPORT_BATCH_SIZE = 500


def money(value) -> str:
    return format(Decimal(value or 0), '.6f')


def user_name(user: User) -> str:
    return user.nickname or (localized_message('微信用户') if user.username.startswith('qiling-') else user.username)


class BillingStatements:
    async def parties(self) -> dict:
        teams = await Team.all().order_by('id').values('id', 'name')
        users = {u.id: user_name(u) for u in await User.all().order_by('id')}
        # Historical attribution remains searchable after a user account is removed.
        historical = await ModelUsageRecord.filter(user_id__not_isnull=True).distinct().values_list('user_id', flat=True)
        for id in historical:
            users.setdefault(id, localized_message('已删除用户'))
        return {'teams': teams, 'users': [{'id': id, 'name': name} for id, name in users.items()]}

    async def query(self, filters: StatementFilters):
        snapshot_id = filters.snapshot_id
        if snapshot_id is None:
            latest = await BalanceTransaction.all().order_by('-id').first()
            snapshot_id = latest.id if latest else 0
        query = BalanceTransaction.filter(type='consume', id__lte=snapshot_id)
        if filters.team_id is not None:
            query = query.filter(team_id=filters.team_id)
        if filters.user_id is not None:
            usages = ModelUsageRecord.filter(user_id=filters.user_id)
            query = query.filter(usage_record_id__in=Subquery(usages.values('id')))
        if filters.start_date:
            query = query.filter(created_at__gte=datetime.combine(filters.start_date, time.min, settings.tz))
        if filters.end_date:
            query = query.filter(created_at__lt=datetime.combine(filters.end_date + timedelta(days=1), time.min, settings.tz))
        return query, snapshot_id

    async def rows(self, transactions: list[BalanceTransaction]) -> list[StatementRowOut]:
        ids = [t.usage_record_id for t in transactions if t.usage_record_id is not None]
        usages = {u.id: u for u in await ModelUsageRecord.filter(id__in=ids)}
        teams = {t.id: t.name for t in await Team.filter(id__in={t.team_id for t in transactions})}
        users = {u.id: user_name(u) for u in await User.filter(id__in={u.user_id for u in usages.values() if u.user_id})}
        novels = {n.id: n.name for n in await Novel.with_deleted().filter(id__in={u.novel_id for u in usages.values()})}
        tasks = {t.id: t.status for t in await AiTask.filter(id__in={u.ai_task_id for u in usages.values() if u.ai_task_id})}
        videos = {v.id: v.status for v in await Video.filter(id__in={u.video_id for u in usages.values() if u.video_id})}
        rows = []
        for t in transactions:
            u = usages.get(t.usage_record_id)
            status = videos.get(u.video_id, tasks.get(u.ai_task_id, u.status)) if u else None
            rows.append(StatementRowOut(
                id=t.id, created_at=t.created_at.astimezone(settings.tz).strftime(settings.DATETIME_FORMAT),
                team_id=t.team_id, team_name=teams.get(t.team_id, localized_message('已删除团队')),
                user_id=u.user_id if u else None,
                user_name=users.get(u.user_id, localized_message('已删除用户')) if u and u.user_id else None,
                novel_id=u.novel_id if u else None,
                novel_name=novels.get(u.novel_id, localized_message('（已删除项目）')) if u else None,
                usage_record_id=t.usage_record_id, billing_type=u.billing_type if u else None,
                task_type=u.task_type if u else None, task_status=status, video_id=u.video_id if u else None,
                usage={k: u.usage[k] for k in SAFE_USAGE_FIELDS if k in (u.usage or {})} if u else {},
                cost=money(-t.change_amount), balance_after=money(t.balance_after),
            ))
        return rows

    async def list(self, filters: StatementFilters, page: int, page_size: int) -> dict:
        query, snapshot_id = await self.query(filters)
        totals = (await query.annotate(total=Sum('change_amount'), count=Count('id')).values('total', 'count'))[0]
        count = totals['count']
        transactions = await query.order_by('-id').offset((page - 1) * page_size).limit(page_size)
        team = await Team.get_or_none(id=filters.team_id) if filters.team_id else None
        return {'items': await self.rows(transactions), 'snapshot_id': snapshot_id,
                'summary': {'total_cost': money(-Decimal(totals['total'] or 0)), 'total_transactions': count,
                            'team_balance': money(team.balance) if team else None},
                'pagination': {'total': count, 'page': page, 'page_size': page_size,
                               'pages': (count + page_size - 1) // page_size}}

    async def export(self, filters: StatementFilters):
        query, _ = await self.query(filters)
        headers = ('流水号', '时间（北京时间）', '团队编号', '团队', '用户编号', '用户', '项目编号', '项目',
                   '账单号', '费用类别', '任务', '任务状态', '视频编号', '用量', '实际扣款（元）', '扣后团队余额（元）')
        yield '\ufeff' + self.csv_row([localized_message(h) for h in headers])
        before = None
        while True:
            batch = await (query.filter(id__lt=before) if before is not None else query).order_by('-id').limit(EXPORT_BATCH_SIZE)
            if not batch:
                break
            for row in await self.rows(batch):
                category = {'text': '文本', 'image': '生图', 'video': '视频', 'media_processing': '画质增强', 'asr': '语音识别'}.get(row.billing_type)
                task = AiTaskTypeEnum(row.task_type).nickname if row.task_type in AiTaskTypeEnum.values() else ''
                status = TaskStatusEnum(row.task_status).nickname if row.task_status in TaskStatusEnum.values() else localized_message('未记录')
                yield self.csv_row([row.id, row.created_at, row.team_id, row.team_name, row.user_id, row.user_name,
                    row.novel_id, row.novel_name, row.usage_record_id, localized_message(category) if category else '',
                    localized_message(task), localized_message(status), row.video_id, self.usage_text(row), Decimal(row.cost), Decimal(row.balance_after)])
            before = batch[-1].id

    @staticmethod
    def usage_text(row: StatementRowOut) -> str:
        u = row.usage
        if row.billing_type == 'text':
            return f"input_tokens={u.get('input_tokens', 0)}, output_tokens={u.get('output_tokens', 0)}"
        if row.billing_type == 'image':
            return f"{u.get('image_count', 0)} {localized_message('张')} {u.get('clarity', '')}"
        seconds = u.get('seconds', u.get('duration_seconds'))
        return f"{seconds}s {u.get('resolution', '')}".strip() if seconds is not None else ''

    @staticmethod
    def csv_row(values: list) -> str:
        # Customer-controlled labels must not become executable spreadsheet formulas.
        def safe(value):
            if value is None:
                return ''
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                return "'" + value
            return value
        stream = io.StringIO(newline='')
        csv.writer(stream).writerow([safe(v) for v in values])
        return stream.getvalue()


billing_statements = BillingStatements()
