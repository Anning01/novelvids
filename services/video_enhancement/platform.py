"""Platform enhancement transport and authenticated settlement receipts."""
from pathlib import Path
from uuid import UUID, uuid5

import httpx

from models.config import AiModelConfig
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from schemas.platform_billing import PlatformReceiptOut
from services.billing.platform import begin_platform_call, capture_platform_response, settle_platform_call
from services.video_enhancement.provider import MediaKitClient, MediaKitError
from utils.messages import localized_message


def request_key(task_id):
    return uuid5(UUID(str(task_id)), 'media:enhance_export')


class PlatformMediaKitClient(MediaKitClient):
    def __init__(self, snapshot, config, *, http, task_id=None):
        super().__init__(snapshot['base_url'], config.api_key, http=http)
        self.snapshot = snapshot
        self.task_id = task_id
        self.headers['X-Cat-Model'] = config.model

    async def upload(self, path: Path, *, max_bytes: int) -> str:
        from services.oss.studio_client import studio_client
        from services.video.base import VideoProviderError
        if path.stat().st_size > max_bytes:
            raise MediaKitError(localized_message('原片超过配置的临时上传大小上限'), definite_rejection=True)
        try:
            client = studio_client(self.snapshot.get('team_id'), base_url=self.base_url, api_key=self.api_key)
            if client is None:
                raise MediaKitError(localized_message('增强服务不可用'), definite_rejection=True)
            return await client.resolve_for_generation(path)
        except VideoProviderError:
            raise MediaKitError(localized_message('MediaKit 原片临时上传失败')) from None

    async def submit(self, video_url, client_token, *, queue_id=None, resolution='1080p'):
        if self.task_id is None:
            raise ValueError('Platform enhancement requires an attributed task')
        # Freeze the admitted pricing, not an administrator's later changes.
        try:
            row = await begin_platform_call(AiModelConfig(**self.snapshot), billing_type='media_processing',
                task_id=self.task_id, request_key=request_key(self.task_id))
        except Exception:
            # No external request has started; release the reserved submission slot.
            raise MediaKitError(localized_message('增强服务不可用'), definite_rejection=True) from None
        payload = {'video_url': video_url, 'resolution': resolution, 'client_token': client_token}
        try:
            response = await self.http.post(self.base_url + '/api/v1/tools/enhance-video-generative',
                headers={**self.headers, 'Idempotency-Key': str(row.request_key)}, json=payload)
            await capture_platform_response(row, response)
            if response.status_code in {400, 401, 402, 403, 404, 413, 415, 422, 429}:
                raise MediaKitError(localized_message('MediaKit 拒绝请求（HTTP {p0}）', p0=response.status_code),
                    definite_rejection=True, status_code=response.status_code)
            response.raise_for_status()
            result = response.json()
            task_id = result.get('task_id') if isinstance(result, dict) and result.get('success') is True else None
            if not isinstance(task_id, str) or not task_id:
                raise MediaKitError(localized_message('增强服务未返回任务编号，可以重新生成'))
            self.last_request_id = str((await StudioCall.get(id=row.id)).platform_request_id or '') or None
            return task_id
        except (httpx.HTTPError, ValueError):
            raise MediaKitError(localized_message('增强服务请求失败，可以重试')) from None


async def settle_platform_enhancement(task, export):
    from controllers.config import ai_model_config_controller
    row = await StudioCall.get(request_key=request_key(task.id))
    ledger = await ModelUsageRecord.get(id=row.usage_record_id)
    if ledger.settlement_status != 'settled':
        snapshot = task.request_params['config_snapshot']
        config = await ai_model_config_controller.get_configured_for_task(8, snapshot['id'],
            team_id=task.request_params.get('team_id'))
        # Validate the frozen destination before sending the current credential.
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as http:
            client = MediaKitClient.for_snapshot(snapshot, config, http=http)
            response = await http.get(client.base_url + '/requests',
                params={'request_key': str(row.request_key)}, headers={'Authorization': 'Bearer ' + client.api_key})
            response.raise_for_status()
            receipt = PlatformReceiptOut.model_validate(response.json())
        if row.platform_request_id is None:
            await StudioCall.filter(id=row.id, platform_request_id=None).update(platform_request_id=receipt.id)
        await settle_platform_call(row.id, receipt)
        await ledger.refresh_from_db()
    if ledger.settlement_status != 'settled':
        raise RuntimeError('Platform enhancement settlement is pending')
    ledger.status = 3 if export.provider_result['status'] == 'completed' else 4
    ledger.usage = {**ledger.usage, 'missing_usage': False, 'export_id': export.id,
                    'external_task_id': export.provider_task_id}
    await ledger.save(update_fields=['status', 'usage', 'updated_at'])
    return ledger
