"""Check execution limits and checkpoint each real model request's usage."""

import dataclasses
import json
import time
from contextlib import asynccontextmanager

from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.wrapper import WrapperModel

from models.creation_agent import AgentMessage


class RecordedAgentModel(WrapperModel):
    def __init__(self, model, *, message: AgentMessage, before_request, max_characters: int,
                 request_limit: int | None = None, total_tokens_limit: int | None = None):
        super().__init__(model)
        self.message = message
        self.before_request = before_request
        self.max_characters = max_characters
        self.calls = list((message.usage or {}).get("calls", []))
        self.request_limit = request_limit
        self.total_tokens_limit = total_tokens_limit

    async def _begin(self, messages, parameters):
        await self.before_request()
        if self.request_limit is not None and len(self.calls) >= self.request_limit:
            raise ValueError("本轮模型调用次数已达到配置上限")
        used = sum(call.get('usage', {}).get('input_tokens', 0) + call.get('usage', {}).get('output_tokens', 0) for call in self.calls)
        if self.total_tokens_limit is not None and used >= self.total_tokens_limit:
            raise ValueError("本轮 token 消耗已达到配置上限")
        tool_characters = sum(len(json.dumps(tool.parameters_json_schema, ensure_ascii=False)) + len(tool.description or '')
                              for tool in [*parameters.function_tools, *parameters.output_tools])
        if len(ModelMessagesTypeAdapter.dump_json(messages).decode()) + tool_characters > self.max_characters:
            raise ValueError("上下文超过配置上限，请缩小选择范围；关键约束未被丢弃")
        call = {"index": len(self.calls) + 1, "status": "in_progress", "usage_reported": False}
        self.calls.append(call)
        await self._checkpoint()
        return call, time.monotonic()

    async def _finish(self, call, started, usage, completed):
        call.update(status="completed" if completed else "failed", duration_seconds=round(time.monotonic() - started, 3))
        if usage is not None:
            call["usage"] = dataclasses.asdict(usage)
            call["usage_reported"] = bool(usage.input_tokens or usage.output_tokens)
        await self._checkpoint()

    async def _checkpoint(self):
        usage = {
            "calls": self.calls,
            "requests": len(self.calls),
            "missing_usage": any(not call["usage_reported"] for call in self.calls),
            "input_tokens": sum(call.get("usage", {}).get("input_tokens", 0) for call in self.calls),
            "output_tokens": sum(call.get("usage", {}).get("output_tokens", 0) for call in self.calls),
        }
        self.message.usage = usage
        await AgentMessage.filter(id=self.message.id).update(usage=usage)

    async def request(self, messages, model_settings, model_request_parameters):
        call, started = await self._begin(messages, model_request_parameters)
        response = None
        try:
            response = await self.wrapped.request(messages, model_settings, model_request_parameters)
            return response
        finally:
            await self._finish(call, started, response.usage if response else None, response is not None)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        call, started = await self._begin(messages, model_request_parameters)
        response = None
        completed = False
        try:
            async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as response:
                yield response
            completed = True
        finally:
            await self._finish(call, started, response.usage() if response else None, completed)
