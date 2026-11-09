import csv
import io
from datetime import datetime
from decimal import Decimal

import pytest

from auth.deps import AuthContext, get_auth_context
from auth.models import BalanceTransaction, Team, User
from config import settings
from main import app
from models.ai_task import AiTask
from models.config import GeneralConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from models.chapter import Chapter
from models.scene import Scene
from models.video import Video
from schemas.billing import StatementFilters
from services.billing.statements import billing_statements


@pytest.fixture
def statement_admin(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    yield
    app.dependency_overrides.pop(get_auth_context, None)


async def charge(team, user, amount='0.430583', *, at=None, task=None):
    novel, _ = await Novel.get_or_create(name='项目', team_id=team.id)
    usage = await ModelUsageRecord.create(novel_id=novel.id, team_id=team.id, user_id=user.id,
        task_type=8, billing_type='media_processing', model='private-supplier', model_name='private-channel',
        usage={'seconds': 5.167, 'resolution': '1080p', 'provider_url': 'https://private.example', 'api_key': 'private-key'},
        pricing_snapshot={'private_cost': 99}, cost=Decimal(amount), ai_task_id=task.id if task else None)
    txn = await BalanceTransaction.create(team=team, type='consume', change_amount=-Decimal(amount),
        balance_after=Decimal('2.231723'), usage_record_id=usage.id, note='private-note')
    if at:
        await BalanceTransaction.filter(id=txn.id).update(created_at=at)
    return txn, usage


@pytest.mark.asyncio
async def test_statement_filters_exact_ledger_and_privacy(client, statement_admin):
    team = await Team.create(name='账单团队', balance=Decimal('2.231723'))
    other = await Team.create(name='另一团队')
    user = await User.create(username='qiling-private-account', nickname='客户')
    second = await User.create(username='second')
    task = await AiTask.create(task_type=8, status=4)
    t, u = await charge(team, user, task=task)
    await charge(team, second, '0.100000')
    await charge(other, user, '0.200000')
    # Calls without balance debits (including team keys) never become actual deductions.
    await ModelUsageRecord.create(novel_id=u.novel_id, team_id=team.id, user_id=user.id,
        task_type=4, billing_type='video', model='private', cost=50, cost_source='team_key')
    await BalanceTransaction.create(team=team, type='topup', change_amount=10, balance_after=10)
    response = await client.get(f'/api/billing/statements?team_id={team.id}&user_id={user.id}&page_size=1')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['summary'] == {'total_cost': '0.430583', 'total_transactions': 1, 'team_balance': '2.231723'}
    assert data['items'][0]['id'] == t.id
    assert data['items'][0]['task_status'] == 4  # A failed collector may already have a real debit.
    assert data['items'][0]['usage'] == {'seconds': 5.167, 'resolution': '1080p'}
    assert not any(secret in response.text for secret in ['private', 'pricing_snapshot', 'model_config', 'api_key'])
    whole = (await client.get('/api/billing/statements')).json()['data']
    assert whole['summary']['total_cost'] == '0.730583'
    cross_team = (await client.get(f'/api/billing/statements?user_id={user.id}')).json()['data']
    assert cross_team['summary']['total_cost'] == '0.630583'
    # Legacy usage may lack a team snapshot; the immutable debit owns the team attribution.
    await ModelUsageRecord.filter(id=u.id).update(team_id=None)
    legacy = (await client.get(f'/api/billing/statements?team_id={team.id}&user_id={user.id}')).json()['data']
    assert legacy['summary']['total_cost'] == '0.430583'


@pytest.mark.asyncio
async def test_statement_export_all_pages_and_stable_snapshot(client, statement_admin, monkeypatch):
    import services.billing.statements as module
    monkeypatch.setattr(module, 'EXPORT_BATCH_SIZE', 2)
    team = await Team.create(name='=HYPERLINK("bad")')
    user = await User.create(username='user', nickname='+malicious')
    for i in range(3):
        await charge(team, user, '0.123456', at=datetime(2026, 11, 9, 23, 59, i, tzinfo=settings.tz))
    await charge(team, user, '9', at=datetime(2026, 11, 10, tzinfo=settings.tz))
    args = f'team_id={team.id}&user_id={user.id}&start_date=2026-11-09&end_date=2026-11-09'
    page = (await client.get(f'/api/billing/statements?{args}&page_size=1')).json()['data']
    assert page['pagination']['total'] == 3
    assert page['summary']['total_cost'] == '0.370368'
    await charge(team, user, '3', at=datetime(2026, 11, 9, tzinfo=settings.tz))
    response = await client.get(f'/api/billing/statements/export?{args}&snapshot_id={page["snapshot_id"]}')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/csv')
    rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows) == 4
    assert rows[1][3].startswith("'=") and rows[1][5].startswith("'+")
    assert sum(Decimal(row[-2]) for row in rows[1:]) == Decimal('0.370368')
    assert 'private' not in response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_statement_missing_usage_and_deleted_user_retained(client, statement_admin):
    team = await Team.create(name='历史团队')
    user = await User.create(username='gone')
    t, _ = await charge(team, user)
    await user.delete()
    orphan = await BalanceTransaction.create(team=team, type='consume', change_amount=Decimal('-.100001'), balance_after=-1)
    response = (await client.get('/api/billing/statements')).json()['data']
    assert response['summary']['total_cost'] == '0.530584'
    assert response['items'][0]['id'] == orphan.id and response['items'][0]['user_id'] is None
    assert response['items'][1]['id'] == t.id and response['items'][1]['user_name']
    parties = (await client.get('/api/billing/statements/parties')).json()['data']
    assert user.id in [u['id'] for u in parties['users']]
    assert await BalanceTransaction.all().count() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/statements', '/statements/parties', '/statements/export'])
async def test_statement_denies_non_super_admin_even_with_team_and_user_filters(client, monkeypatch, path):
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(team_id=1)
    try:
        response = await client.get(f'/api/billing{path}?team_id=2&user_id=3')
        assert response.status_code == 403 or response.json()['code'] == 403
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.asyncio
async def test_statement_validates_dates_and_pagination(client, statement_admin):
    for query in ['start_date=2026-11-10&end_date=2026-11-09', 'team_id=0', 'page_size=101', 'start_date=bad']:
        response = await client.get(f'/api/billing/statements?{query}')
        assert response.status_code == 422 or response.json()['code'] == 422
    empty = await billing_statements.list(StatementFilters(), 1, 20)
    assert empty['summary']['total_cost'] == '0.000000'
    assert empty['pagination']['total'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [True, False])
async def test_statement_denies_unauthenticated_and_anonymous_edition(client, monkeypatch, enabled):
    monkeypatch.setattr(settings, 'AUTH_ENABLED', enabled)
    response = await client.get('/api/billing/statements')
    assert response.status_code in (401, 403) or response.json()['code'] in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_statement_exports_each_usage_kind_and_current_video_result(client, statement_admin, language):
    await GeneralConfig.create(id=1, prompt_language=language)
    team = await Team.create(name='分类团队')
    user = await User.create(username='classification')
    for kind, payload in [('text', {'input_tokens': 123, 'output_tokens': 45}),
                          ('image', {'image_count': 1, 'clarity': '2K'}),
                          ('asr', {'duration_seconds': 5.5}), ('video', {'seconds': 5, 'resolution': '480p'})]:
        _, u = await charge(team, user)
        u.billing_type = kind
        u.task_type = {'text': 7, 'image': 2, 'asr': 9, 'video': 4}[kind]
        u.usage = payload
        if kind == 'video':
            chapter = await Chapter.create(novel_id=u.novel_id, number=1, name='第1集', content='')
            scene = await Scene.create(chapter=chapter, sequence=1)
            video = await Video.create(scene=scene, model_type=1, status=3, url='https://private.example/video')
            u.video_id = video.id
            u.status = 4
        await u.save()
    data = (await client.get('/api/billing/statements')).json()['data']
    assert data['items'][0]['task_status'] == 3
    export = await client.get('/api/billing/statements/export')
    assert 'input_tokens=123, output_tokens=45' in export.text
    assert ('1 张 2K' if language == 'zh' else '1 images 2K') in export.text
    assert '5.5s' in export.text and '5s 480p' in export.text
    if language == 'en':
        headers = next(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))))
        assert headers == ['Transaction ID', 'Time (Beijing)', 'Team ID', 'Team', 'User ID', 'User',
            'Project ID', 'Project', 'Billing record ID', 'Charge category', 'Task', 'Task status',
            'Video ID', 'Usage', 'Actual deduction (CNY)', 'Team balance after deduction (CNY)']
    assert 'private' not in export.text
