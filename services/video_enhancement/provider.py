"""AI MediaKit protocol; transport errors never expose credentials or media URLs."""

from urllib.parse import quote
from urllib.parse import urlsplit
from pathlib import Path
import asyncio

import httpx
from pydantic import BaseModel, Field, ValidationError
from utils.messages import localized_message


class MediaKitError(RuntimeError):
    def __init__(self, message: str, *, definite_rejection: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.definite_rejection = definite_rejection
        self.status_code = status_code


class MediaKitTask(BaseModel):
    task_id: str = Field(min_length=1)
    status: str
    result: dict | None = None
    error: dict | None = None
    expires_at: int | None = None


class MediaKitClient:
    def __init__(self, base_url: str, api_key: str, *, http: httpx.AsyncClient):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.http = http
        self.last_request_id: str | None = None

    @classmethod
    def for_snapshot(cls, snapshot, config, *, http):
        if any(str(getattr(config, key)).rstrip('/') != str(snapshot[key]).rstrip('/')
               for key in ('base_url', 'api_protocol', 'model')):
            raise MediaKitError(localized_message('增强服务地址或协议已变化，请恢复该任务原配置后继续'), definite_rejection=True)
        return cls(snapshot['base_url'], config.api_key, http=http)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.http.request(method, self.base_url + path,
                headers={'Authorization': 'Bearer ' + self.api_key}, **kwargs)
            if response.status_code in {400, 401, 403, 404, 410, 413, 415, 422, 429}:
                raise MediaKitError(localized_message('MediaKit 拒绝请求（HTTP {p0}）',p0=response.status_code), definite_rejection=True, status_code=response.status_code)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload,dict) and isinstance(payload.get('request_id'),str):
                self.last_request_id = payload['request_id']
            if not isinstance(payload, dict) or payload.get('success') is not True:
                raise MediaKitError(localized_message('MediaKit 未接受请求'))
            return payload
        except MediaKitError:
            raise
        except (httpx.HTTPError, ValueError):
            raise MediaKitError(localized_message('MediaKit 请求失败，请先核对任务回执')) from None

    async def submit(self, video_url: str, client_token: str, *, queue_id: str | None = None) -> str:
        payload = {'video_url': video_url, 'resolution': '1080p', 'client_token': client_token}
        if queue_id:
            payload['queue_id'] = queue_id
        result = await self._request('POST', '/api/v1/tools/enhance-video-generative', json=payload)
        task_id = result.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            raise MediaKitError(localized_message('MediaKit 回执缺少任务编号，请核对提交结果'))
        return task_id

    async def query(self, task_id: str) -> MediaKitTask:
        result = await self._request('GET', '/api/v1/tasks/' + quote(task_id, safe=''))
        try:
            task = MediaKitTask.model_validate(result)
        except ValidationError:
            raise MediaKitError(localized_message('MediaKit 返回了无效任务回执')) from None
        if task.task_id != task_id or task.status not in {'running', 'processing', 'completed', 'failed'}:
            raise MediaKitError(localized_message('MediaKit 返回的任务回执不一致'))
        return task

    async def upload(self, path: Path, *, max_bytes: int) -> str:
        if path.stat().st_size > max_bytes:
            raise MediaKitError(localized_message('原片超过配置的临时上传大小上限'), definite_rejection=True)
        receipt = await self._request('POST', '/api/v1/tools-sync/request-media-upload-url', json={})
        result = receipt.get('result') or {}
        url, file_id = result.get('upload_url', ''), result.get('file_id', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or result.get('method') != 'PUT' or not file_id.startswith('mediakit://'):
            raise MediaKitError(localized_message('MediaKit 上传回执无效'))
        headers = {'Content-Type': 'video/mp4'}
        for header in result.get('upload_headers') or []:
            if not isinstance(header, dict) or not isinstance(header.get('key'), str) or not isinstance(header.get('value'), str):
                raise MediaKitError(localized_message('MediaKit 上传请求头无效'))
            if header['key'].lower() in {'host', 'authorization', 'cookie'}:
                raise MediaKitError(localized_message('MediaKit 返回了不允许的上传请求头'))
            headers[header['key']] = header['value']
        async def content():
            with path.open('rb') as source:
                while block := await asyncio.to_thread(source.read, 1024 * 1024):
                    yield block
        try:
            response = await self.http.put(url, content=content(), headers=headers, timeout=300)
            response.raise_for_status()
        except httpx.HTTPError:
            raise MediaKitError(localized_message('MediaKit 原片临时上传失败')) from None
        return file_id
