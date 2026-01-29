"""LLM 客户端服务。

提供与 OpenAI 兼容的 LLM API 客户端，支持结构化输出和续写模式。
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """兼容 OpenAI API 的 LLM 客户端。

    支持：
    - 结构化输出 (response_format: json_schema)
    - 续写模式 (处理长输出被截断的情况)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-4o-mini",
        timeout: float = 300.0,  # 5分钟超时
    ):
        from openai import AsyncOpenAI
        import httpx

        # 设置 httpx 超时
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0))
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        self.model_name = model_name
        self.timeout = timeout

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 16000,
    ) -> str:
        """通用的 LLM 完成方法。"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def complete_json(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        system: str | None = None,
        max_tokens: int = 16000,
        max_continuations: int = 3,
    ) -> dict[str, Any]:
        """结构化 JSON 输出，支持续写模式处理长输出。

        Args:
            prompt: 用户提示词
            json_schema: JSON Schema 定义输出结构
            system: 系统提示词
            max_tokens: 单次最大输出 token 数
            max_continuations: 最大续写次数

        Returns:
            解析后的 JSON 对象
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        logger.info(f"[LLM] 开始调用 {self.model_name}, max_tokens={max_tokens}, timeout={self.timeout}s")
        logger.info(f"[LLM] Prompt 长度: {len(prompt)} 字符")

        accumulated_content = ""
        continuations = 0
        total_start = time.time()

        while continuations <= max_continuations:
            request_start = time.time()
            logger.info(f"[LLM] 发送请求 (续写次数: {continuations})... 等待响应中...")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": json_schema.get("title", "response"),
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            request_duration = time.time() - request_start
            logger.info(f"[LLM] 请求完成，耗时 {request_duration:.1f}s")

            choice = response.choices[0]
            content = choice.message.content or ""
            accumulated_content += content

            # 记录 token 使用情况
            usage = response.usage
            if usage:
                logger.info(f"[LLM] Token 使用: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")

            # 检查是否完成
            finish_reason = choice.finish_reason
            logger.info(f"[LLM] finish_reason={finish_reason}, 本次响应长度={len(content)} 字符")

            if finish_reason == "stop":
                # 正常完成
                total_duration = time.time() - total_start
                logger.info(f"[LLM] ✅ 正常完成，累积响应长度={len(accumulated_content)} 字符，总耗时 {total_duration:.1f}s")
                break
            elif finish_reason == "length":
                # 输出被截断，需要续写
                continuations += 1
                logger.warning(f"[LLM] ⚠️ 输出被截断，准备续写 ({continuations}/{max_continuations})...")
                if continuations > max_continuations:
                    logger.warning(f"[LLM] ❌ 已达最大续写次数，停止续写")
                    break

                # 添加助手的部分回复，让模型继续
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "继续输出，从你上次停止的地方继续，保持 JSON 格式。"
                })
            else:
                # 其他原因（如 content_filter）
                logger.warning(f"[LLM] ⚠️ 非预期的 finish_reason: {finish_reason}")
                break

        # 尝试解析累积的 JSON
        logger.info(f"[LLM] 开始解析 JSON (长度: {len(accumulated_content)} 字符)...")
        result = self._parse_json_response(accumulated_content)
        shots_count = len(result.get("shots", []))
        logger.info(f"[LLM] ✅ JSON 解析成功，包含 {shots_count} 个镜头")
        return result

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """解析 JSON 响应，处理各种格式问题。"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 代码块
        import re
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到 { 和 } 之间的内容
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # 解析失败
        raise ValueError(f"Failed to parse JSON response: {text[:500]}")
