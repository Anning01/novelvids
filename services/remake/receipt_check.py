"""Manual retry for legacy inline-video calls rejected before CAT API admission."""
import re
from uuid import uuid5

import httpx

from models.ai_task import AiTask
from models.config import AiModelConfig
from models.creation_agent import AgentMessage
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord


async def rejected_inline_upload(task, operations):
    if len(operations) != 1 or not task or task.stage != "needs_review":
        return False
    operation = operations[0]
    if operation.state != "uncertain" or operation.key != "model:remake:RemakeAssets:1":
        return False
    child = await AiTask.get_or_none(id=uuid5(task.id, operation.key))
    if not child or child.request_params.get("parent_task_id") != str(task.id) or child.response_data:
        return False
    message = await AgentMessage.get_or_none(task=child, role="assistant")
    if not message:
        return False
    calls = (message.usage or {}).get("calls", [])
    if len(calls) != 1 or calls[0].get("status") != "failed" or calls[0].get("platform_request_id"):
        return False
    media = [item for msg in message.native_messages for part in msg.get("parts", [])
             if isinstance(part.get("content"), list) for item in part["content"] if isinstance(item, str)]
    if not any(re.fullmatch(r"\[video/[\w.+-]+; bytes=\d+; sha256=[0-9a-f]{64}\]", item)
               and int(item.split("bytes=")[1].split(";")[0]) > 1024 * 1024 for item in media):
        return False
    call = await StudioCall.get_or_none(id=calls[0].get("studio_call_id"), message_id=message.id, platform_request_id=None)
    if not call or not await ModelUsageRecord.filter(id=call.usage_record_id, ai_task_id=child.id).exists():
        return False
    config = await AiModelConfig.get_or_none(id=call.model_config_id, api_protocol="novelvids")
    if not config or config.base_url.rstrip("/") != call.base_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(call.base_url + "/requests", params={"request_key": str(call.request_key)},
                headers={"Authorization": "Bearer " + config.api_key})
        body = response.json() if response.status_code == 404 else {}
        return isinstance(body, dict) and isinstance(body.get("error"), dict) and body["error"].get("message") == "请求不存在"
    except (httpx.HTTPError, ValueError):
        return False
