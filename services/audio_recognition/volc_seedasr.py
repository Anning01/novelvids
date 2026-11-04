"""火山引擎录音文件识别大模型 2.0 (SeedASR) 异步识别客户端。

官方文档: https://docs.volcengine.com/docs/doubao-voice/large-model-recording-file-recognition-standard-version-api?lang=zh
资源标识: volc.seedasr.auc
"""
import asyncio
import base64
import logging
import uuid
from typing import Any
import httpx

from utils.messages import localized_message as msg

logger = logging.getLogger(__name__)

STATUS_SUCCESS = "20000000"
STATUS_PROCESSING = "20000001"
STATUS_QUEUED = "20000002"


class VolcSeedAsrClient:
    """火山引擎录音文件识别 2.0 API 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openspeech.bytedance.com/api/v3/auc/bigmodel",
        model: str = "volc.seedasr.auc",
        timeout: float = 120.0,
        poll_interval: float = 0.8,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or "volc.seedasr.auc"
        self.timeout = timeout
        self.poll_interval = poll_interval

    def _parse_keys(self) -> tuple[str, str]:
        """支持 app_id:token、app_id;token 或单一 api_key。"""
        raw = self.api_key
        if ":" in raw:
            app_id, token = raw.split(":", 1)
            return app_id.strip(), token.strip()
        if ";" in raw:
            app_id, token = raw.split(";", 1)
            return app_id.strip(), token.strip()
        return "", raw

    def _build_headers(self, request_id: str) -> dict[str, str]:
        app_id, token = self._parse_keys()
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.model,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        if app_id:
            headers["X-Api-App-Key"] = app_id
            headers["X-Api-Access-Key"] = token
        elif token:
            headers["X-Api-Key"] = token
        return headers

    async def recognize(
        self,
        *,
        audio_bytes: bytes | None = None,
        audio_url: str | None = None,
        format: str = "mp3",
    ) -> list[dict[str, Any]]:
        """提交音频并轮询查询识别结果。

        返回分句列表，每项包含:
        - text: str (识别文本)
        - start_time: int (起始毫秒)
        - end_time: int (结束毫秒)
        """
        if not audio_bytes and not audio_url:
            raise ValueError(msg("必须提供音频数据或音频 URL"))

        request_id = str(uuid.uuid4())
        headers = self._build_headers(request_id)
        app_id, _ = self._parse_keys()

        payload: dict[str, Any] = {
            "user": {"uid": app_id or "novelvids_studio"},
            "audio": {"format": format},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
            },
        }

        if audio_url:
            payload["audio"]["url"] = audio_url
        else:
            assert audio_bytes is not None
            payload["audio"]["data"] = base64.b64encode(audio_bytes).decode("utf-8")
            payload["audio"]["format"] = format

        submit_url = f"{self.base_url}/submit"
        query_url = f"{self.base_url}/query"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. 提交任务
            logger.info(
                "volc_seedasr_submit model=%s request_id=%s has_url=%s bytes_len=%s",
                self.model,
                request_id,
                bool(audio_url),
                len(audio_bytes) if audio_bytes else 0,
            )
            submit_resp = await client.post(submit_url, json=payload, headers=headers)
            submit_status = submit_resp.headers.get("X-Api-Status-Code") or ""
            # Status/log IDs are sufficient diagnostics. Response bodies can echo credentials.
            submit_msg = submit_resp.headers.get("X-Tt-Logid", "")

            if submit_resp.status_code >= 400 or (
                submit_status and submit_status not in (STATUS_SUCCESS, STATUS_PROCESSING, STATUS_QUEUED)
            ):
                logger.error(
                    "volc_seedasr_submit_failed status=%s code=%s msg=%s",
                    submit_resp.status_code,
                    submit_status,
                    submit_msg,
                )
                raise RuntimeError(msg("提交语音识别任务失败，请检查模型配置"))

            # 2. 轮询结果
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout

            query_headers = dict(headers)
            # 部分接口轮询无需 X-Api-Sequence
            query_headers.pop("X-Api-Sequence", None)
            if submit_resp.text:
                submitted = submit_resp.json()
                if isinstance(submitted, dict) and isinstance(submitted.get("task_id"), str):
                    query_headers["X-Api-Request-Id"] = submitted["task_id"]

            while loop.time() < deadline:
                await asyncio.sleep(self.poll_interval)
                query_resp = await client.post(query_url, json={}, headers=query_headers)
                status_code = query_resp.headers.get("X-Api-Status-Code") or ""
                message = query_resp.headers.get("X-Tt-Logid") or ""

                if query_resp.status_code >= 400:
                    raise RuntimeError(msg("查询语音识别结果 HTTP 异常: {p0}", p0=query_resp.status_code))

                if status_code == STATUS_SUCCESS:
                    data = query_resp.json() if query_resp.text else {}
                    result = data.get("result") or {}
                    utterances = result.get("utterances") or []
                    logger.info(
                        "volc_seedasr_done request_id=%s utterances_count=%d",
                        request_id,
                        len(utterances),
                    )
                    return utterances

                if status_code in (STATUS_PROCESSING, STATUS_QUEUED):
                    continue

                # 其他非成功状态
                error_detail = message or status_code
                logger.error("volc_seedasr_error status=%s msg=%s", status_code, error_detail)
                raise RuntimeError(msg("语音识别失败，请稍后重试"))

            raise TimeoutError(msg("语音识别任务超时，请稍后重试"))
