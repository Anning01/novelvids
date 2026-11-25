"""Remote enhancement uses platform uploads, task recovery and authenticated receipts."""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from auth.deps import AuthContext
from config import settings
from controllers.chapter_export import chapter_exports
from models.config import AiModelConfig
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from services.creation_agent.waiting import WaitingForMedia
from services.video_enhancement.handler import EnhanceExportHandler
from services.video_enhancement.platform import PlatformMediaKitClient, request_key
from services.video_enhancement.provider import MediaKitClient, MediaKitError
from services.video_enhancement.recovery import collect_export, recover_export
from services.video_enhancement.settlement import settle_enhancement
from test.test_services.test_video_enhancement_execution import pending_export


async def platform_export():
    task, export, config = await pending_export()
    config.api_protocol = 'novelvids'
    config.scope = 'studio_platform'
    config.model = 'nv-13'
    config.base_url = 'https://platform.example/v1'
    config.api_key = 'nv_fixture'
    await config.save()
    task.request_params['config_snapshot'].update({key: getattr(config, key) for key in
        ('api_protocol', 'scope', 'model', 'base_url', 'pricing')})
    await task.save()
    return task, export, config


def route_http(monkeypatch, respond):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(respond)))


@pytest.mark.asyncio
async def test_catalog_includes_synced_and_direct_services_without_unrelated_models():
    _, _, config = await platform_export()
    direct = await AiModelConfig.create(name='Direct', task_type=8, is_active=True,
        api_protocol='volcengine_mediakit', model='enhance-video-generative', base_url='https://direct.example', api_key='fixture')
    await AiModelConfig.create(name='Video', task_type=4, is_active=True, api_protocol='novelvids',
        model='nv-20', base_url='https://platform.example/v1', api_key='fixture')
    await AiModelConfig.create(name='Inactive', task_type=8, is_active=False, api_protocol='novelvids',
        model='nv-21', base_url='https://platform.example/v1', api_key='fixture')
    assert {row.id for row in await chapter_exports.configs(AuthContext())} == {config.id, direct.id}
    from api.video_export import export_models
    response = await export_models(AuthContext())
    assert {row['id'] for row in response.data} == {config.id, direct.id}


@pytest.mark.asyncio
async def test_private_export_upload_uses_platform_lease_without_public_copy(tmp_path, monkeypatch):
    task, _, config = await platform_export()
    path = tmp_path / 'private-exports' / 'source.mp4'
    path.parent.mkdir(); path.write_bytes(b'private-video')
    resolve = AsyncMock(return_value='https://media.example/temporary.mp4')
    factory = lambda team, **kw: SimpleNamespace(resolve_for_generation=resolve)
    monkeypatch.setattr('services.oss.studio_client.studio_client', factory)
    client = MediaKitClient.for_snapshot(task.request_params['config_snapshot'], config, http=None)
    assert isinstance(client, PlatformMediaKitClient)
    assert await client.upload(path, max_bytes=100) == 'https://media.example/temporary.mp4'
    resolve.assert_awaited_once_with(path)
    from services.oss.studio_client import retain_original
    retained = retain_original(path, tmp_path / 'private-cache')
    assert retained.path.read_bytes() == b'private-video'
    assert retained.content_type == 'video/mp4'
    with pytest.raises(MediaKitError):
        await client.upload(path, max_bytes=1)


@pytest.mark.asyncio
async def test_remote_submission_replay_and_restart_never_submit_twice(monkeypatch):
    task, export, config = await platform_export()
    public_id = uuid4(); seen = []
    def respond(request):
        seen.append(request)
        assert request.url.path == '/v1/api/v1/tools/enhance-video-generative'
        assert request.headers['X-Cat-Model'] == 'nv-13'
        assert request.headers['Idempotency-Key'] == str(request_key(task.id))
        assert json.loads(request.content) == {'video_url': export.source_media_ref,
            'resolution': '1080p', 'client_token': export.identity_key}
        return httpx.Response(200, headers={'X-Cat-Request-Id': str(public_id)},
            json={'success': True, 'task_id': 'remote-task'})
    route_http(monkeypatch, respond)
    for _ in range(2):
        with pytest.raises(WaitingForMedia):
            await EnhanceExportHandler().execute(task.request_params)
    assert len(seen) == 1
    await export.refresh_from_db()
    assert export.provider_task_id == 'remote-task'
    assert await recover_export(task) is False  # Only enhance_export operations are recoverable.
    task.request_params['operation'] = 'enhance_export'
    assert await recover_export(task)
    row = await StudioCall.get()
    assert row.platform_request_id == public_id
    ledger = await ModelUsageRecord.get()
    assert ledger.billing_type == 'media_processing' and ledger.settlement_status == 'pending'
    assert row.local_pricing == task.request_params['config_snapshot']['pricing']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,definite', [(402, True), (429, True), (500, False)])
async def test_platform_submission_errors_are_safe_and_preserve_uncertainty(monkeypatch, status, definite):
    task, export, _ = await platform_export()
    route_http(monkeypatch, lambda _: httpx.Response(status, json={'error': 'nv_secret https://private/?signed=private'}))
    with pytest.raises(MediaKitError) as error:
        await EnhanceExportHandler().execute(task.request_params)
    assert error.value.definite_rejection is definite
    assert 'nv_secret' not in str(error.value) and 'signed=private' not in str(error.value)
    await export.refresh_from_db()
    assert export.submission_slot is (not definite)
    if status in {402, 429}:
        ledger = await ModelUsageRecord.get()
        assert ledger.settlement_status == 'settled' and ledger.platform_cost == 0


@pytest.mark.asyncio
async def test_remote_completion_waits_for_receipt_saves_output_and_settles_once(monkeypatch):
    task, export, config = await platform_export()
    public_id = uuid4(); phase = {'settlement': 'pending'}; counts = {'submit': 0, 'query': 0, 'receipt': 0}
    def respond(request):
        if request.method == 'POST':
            counts['submit'] += 1
            return httpx.Response(200, headers={'X-Cat-Request-Id': str(public_id)},
                json={'success': True, 'task_id': 'remote-task'})
        if request.url.path == '/v1/api/v1/tasks/remote-task':
            assert request.headers['X-Cat-Model'] == config.model
            counts['query'] += 1
            return httpx.Response(200, json={'success': True, 'task_id': 'remote-task', 'status': 'completed',
                'result': {'duration': 5, 'fps': 24, 'resolution': '1080p', 'video_url': 'https://media.example/out.mp4'}})
        assert request.url.path == '/v1/requests'
        assert request.url.params['request_key'] == str(request_key(task.id))
        counts['receipt'] += 1
        return httpx.Response(200, json={'id': str(public_id), 'model': 'nv-13', 'status': 'completed',
            'usage': {'seconds': 5, 'fps': 24, 'short_side': 1080},
            'settlement': {'status': phase['settlement'], 'amount': '0.250000', 'currency': 'CNY'}, 'pricing': {}})
    route_http(monkeypatch, respond)
    with pytest.raises(WaitingForMedia):
        await EnhanceExportHandler().execute(task.request_params)
    await export.refresh_from_db()
    save = AsyncMock(return_value={'ref': '/media/exports/enhanced.mp4', 'sha256': '3'*64,
        'probe': {'duration': '5', 'width': 1920, 'height': 1080, 'fps': '24'}})
    monkeypatch.setattr('services.video_enhancement.recovery.export_media.save_enhanced', save)
    monkeypatch.setattr('services.creation_agent.production.finish_production_message', AsyncMock())
    export.source_video_id = 1
    await export.save()
    apply = AsyncMock()
    monkeypatch.setattr('services.video_enhancement.current_video.apply_enhanced_video', apply)
    await collect_export(export)
    await task.refresh_from_db(); await export.refresh_from_db()
    assert task.stage == 'billing_pending' and export.media_ref and not export.collection_complete
    apply.assert_not_awaited()
    phase['settlement'] = 'settled'
    config.is_active = False; await config.save()  # Disabling new work must not prevent collection.
    await collect_export(export)
    await task.refresh_from_db(); await export.refresh_from_db()
    assert task.status == 3 and export.collection_complete
    apply.assert_awaited_once()
    save.assert_awaited_once()
    first = await settle_enhancement(task, export)
    second = await settle_enhancement(task, export)
    assert first.id == second.id
    assert first.cost == Decimal('0.416667') and first.platform_cost == Decimal('0.25')
    assert first.local_charge == 0 and first.settlement_status == 'settled'
    assert not first.usage['missing_usage']
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert counts == {'submit': 1, 'query': 1, 'receipt': 2}


@pytest.mark.asyncio
async def test_platform_processing_charge_is_atomic_and_not_repeated(monkeypatch):
    from auth.models import Team, User, TeamMember, BalanceTransaction
    from services.billing.platform import begin_platform_call, settle_platform_call
    from schemas.platform_billing import PlatformReceiptOut
    monkeypatch.setattr(settings, 'DEPLOYMENT_ROLE', 'studio')
    task, export, config = await platform_export()
    team = await Team.create(name='enhancement-team', balance=10)
    user = await User.create(username='enhancement-owner')
    await TeamMember.create(team=team, user=user, role='creator')
    task.request_params.update(team_id=team.id, user_id=user.id)
    await task.save()
    row = await begin_platform_call(config, billing_type='media_processing', task_id=task.id,
                                    request_key=request_key(task.id))
    row.platform_request_id = uuid4(); await row.save()
    receipt = PlatformReceiptOut(id=row.platform_request_id, model=config.model, status='completed',
        usage={'seconds': 5, 'short_side': 1080, 'fps': 24},
        settlement={'status': 'settled', 'amount': '0.25'}, pricing={})
    for _ in range(2):
        await settle_platform_call(row.id, receipt)
    ledger = await ModelUsageRecord.get(id=row.usage_record_id)
    await team.refresh_from_db()
    assert team.balance == Decimal('9.583333')
    assert ledger.local_charge == Decimal('0.416667')
    assert await BalanceTransaction.filter(usage_record_id=ledger.id).count() == 1


@pytest.mark.asyncio
async def test_platform_receipt_mismatch_cannot_settle_another_model():
    from services.billing.platform import begin_platform_call, settle_platform_call
    from schemas.platform_billing import PlatformReceiptOut
    task, _, config = await platform_export()
    row = await begin_platform_call(config, billing_type='media_processing', task_id=task.id,
                                    request_key=request_key(task.id))
    row.platform_request_id = uuid4(); await row.save()
    receipt = PlatformReceiptOut(id=row.platform_request_id, model='nv-999', status='completed', usage={},
        settlement={'status': 'settled', 'amount': '0.25'}, pricing={})
    with pytest.raises(ValueError, match='model'):
        await settle_platform_call(row.id, receipt)
    ledger = await ModelUsageRecord.get(id=row.usage_record_id)
    assert ledger.settlement_status == 'pending' and ledger.platform_cost is None


@pytest.mark.asyncio
async def test_local_admission_failure_releases_slot_without_sending(monkeypatch):
    task, export, _ = await platform_export()
    monkeypatch.setattr('services.video_enhancement.platform.begin_platform_call',
                        AsyncMock(side_effect=RuntimeError('database unavailable')))
    def unexpected(_):
        pytest.fail('No external request may start before durable attribution')
    route_http(monkeypatch, unexpected)
    with pytest.raises(MediaKitError) as failure:
        await EnhanceExportHandler().execute(task.request_params)
    assert failure.value.definite_rejection
    await export.refresh_from_db()
    assert not export.submission_slot
