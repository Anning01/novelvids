"""Check execution limits and checkpoint each real model request's usage."""

import dataclasses
import time
from contextlib import asynccontextmanager

from services.creation_agent.context_budget import ContextBudget, wire_size
from schemas.creation_agent import AgentConfiguration
from pydantic_ai.models.wrapper import WrapperModel

from models.creation_agent import AgentMessage


class RecordedAgentModel(WrapperModel):
    def __init__(self, model, *, message: AgentMessage, before_request, max_characters: int,
                 request_limit: int | None = None, total_tokens_limit: int | None = None, limits: AgentConfiguration | None = None, on_compact=None):
        super().__init__(model)
        self.message = message
        self.before_request = before_request
        self.max_characters = max_characters
        self.calls = list((message.usage or {}).get("calls", []))
        self.request_limit = request_limit
        self.total_tokens_limit = total_tokens_limit
        self.phase = 'main'
        self.overflow_retried = False
        self.budget = ContextBudget(limits or AgentConfiguration(max_context_characters=max_characters), message, on_compact)
        self.budget.limits = self.budget.limits.model_copy(update={'max_context_characters': max_characters})

    async def _begin(self, messages, parameters):
        await self.before_request()
        if self.request_limit is not None and len(self.calls) >= self.request_limit:
            raise ValueError("本轮模型调用次数已达到配置上限")
        used = sum(call.get('usage', {}).get('input_tokens', 0) + call.get('usage', {}).get('output_tokens', 0) for call in self.calls)
        if self.total_tokens_limit is not None and used >= self.total_tokens_limit:
            raise ValueError("本轮 token 消耗已达到配置上限")
        report = wire_size(messages, parameters)
        if report['total_characters'] > self.max_characters:
            raise ValueError("上下文超过配置上限，请分段读取当前对象")
        call = {"index": len(self.calls) + 1, "status": "in_progress", "usage_reported": False,
                "phase": self.phase, "context": self.budget.report(messages, parameters)}
        self.calls.append(call)
        await self._checkpoint()
        return call, time.monotonic()

    async def _finish(self, call, started, usage, completed, finish_reason=None):
        call.update(status="completed" if completed else "failed", duration_seconds=round(time.monotonic() - started, 3))
        if finish_reason is not None:
            call['finish_reason'] = finish_reason
        if usage is not None:
            call["usage"] = dataclasses.asdict(usage)
            call["usage_reported"] = bool(usage.input_tokens or usage.output_tokens)
            call["cache_usage_reported"] = bool(usage.details.get('cache_usage_reported', False) or usage.cache_read_tokens or usage.cache_write_tokens)
            self.budget.observe(call['context'], usage)
        await self._checkpoint()

    async def _checkpoint(self):
        usage = {
            "calls": self.calls,
            "requests": len(self.calls),
            "missing_usage": any(not call["usage_reported"] for call in self.calls),
            "input_tokens": sum(call.get("usage", {}).get("input_tokens", 0) for call in self.calls),
            "output_tokens": sum(call.get("usage", {}).get("output_tokens", 0) for call in self.calls),
        }
        usage.update(
            cache_read_tokens=sum(c.get('usage', {}).get('cache_read_tokens', 0) for c in self.calls),
            cache_write_tokens=sum(c.get('usage', {}).get('cache_write_tokens', 0) for c in self.calls),
            cache_usage_reported=bool(self.calls) and all(c.get('cache_usage_reported', False) for c in self.calls),
            summary_requests=sum(c.get('phase') == 'summary' for c in self.calls),
            summary_input_tokens=sum(c.get('usage', {}).get('input_tokens', 0) for c in self.calls if c.get('phase') == 'summary'),
            summary_output_tokens=sum(c.get('usage', {}).get('output_tokens', 0) for c in self.calls if c.get('phase') == 'summary'),
            compactions=self.budget.compactions,
        )
        pricing = (getattr(self.message, 'model_snapshot', None) or {}).get('pricing') or {}
        usage['cache_price_configured'] = pricing.get('cache_input_price_per_1m') is not None
        self.message.usage = usage
        await AgentMessage.filter(id=self.message.id).update(usage=usage)

    def _is_context_overflow(self, exc):
        from pydantic_ai.exceptions import ModelHTTPError
        from openai import BadRequestError
        if not isinstance(exc, (ModelHTTPError, BadRequestError)) or getattr(exc, 'status_code', None) not in (400, 413):
            return False
        body = str(getattr(exc, 'body', '')).lower()
        return any(code in body for code in ('context_length_exceeded', 'context_window_exceeded', 'maximum context length'))

    async def request(self, messages, model_settings, model_request_parameters):
        messages = await self.budget.prepare(messages, model_request_parameters)
        while True:
            call, started = await self._begin(messages, model_request_parameters)
            response = None
            try:
                response = await self.wrapped.request(messages, model_settings, model_request_parameters)
                return response
            except Exception as exc:
                if self.overflow_retried or not self._is_context_overflow(exc):
                    raise
                self.overflow_retried = True
                messages = await self.budget.prepare(messages, model_request_parameters, force=True)
            finally:
                await self._finish(call, started, response.usage if response else None, response is not None,
                                   response.finish_reason if response else None)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        messages = await self.budget.prepare(messages, model_request_parameters)
        while True:
            call, started = await self._begin(messages, model_request_parameters)
            response = None
            entered = completed = False
            try:
                async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as response:
                    entered = True
                    yield response
                completed = True
                return
            except Exception as exc:
                # Once streaming starts the caller may have seen tool deltas.
                # Never replay a partially consumed model response.
                if entered or self.overflow_retried or not self._is_context_overflow(exc):
                    raise
                self.overflow_retried = True
                messages = await self.budget.prepare(messages, model_request_parameters, force=True)
            finally:
                await self._finish(call, started, response.usage() if response else None, completed,
                                   response.finish_reason if response else None)
