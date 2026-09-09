"""Local real-evaluation spend guard; not a replacement for production billing."""

import dataclasses
import json
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.wrapper import WrapperModel

from services.billing.pricing import compute_text_cost


def real_evaluation_configuration(test_env: dict):
    def value(key):
        return test_env.get(key) or os.getenv(key)
    base_url, key, model = [value(f'CREATION_AGENT_{suffix}') for suffix in ('BASE_URL', 'API_KEY', 'MODEL')]
    if not all((base_url, key, model)):
        return None
    pricing = {'type': 'text', 'currency': 'CNY',
               'input_price_per_1m': value('CREATION_AGENT_INPUT_PRICE_CNY_PER_1M'),
               'cache_input_price_per_1m': value('CREATION_AGENT_CACHE_INPUT_PRICE_CNY_PER_1M'),
               'output_price_per_1m': value('CREATION_AGENT_OUTPUT_PRICE_CNY_PER_1M')}
    source = value('CREATION_AGENT_PRICE_SOURCE')
    if not all((pricing['input_price_per_1m'], pricing['output_price_per_1m'], source)):
        raise ValueError('真实调用前必须核实人民币输入/输出单价和来源；尚未发出调用')
    output = Path(__file__).resolve().parents[1] / 'logs' / 'creation-agent-evaluation'
    ledger = EvaluationSpendLedger(output / 'spend.jsonl', pricing)
    thinking = value('CREATION_AGENT_THINKING')
    if thinking not in (None, '', 'enabled', 'disabled'):
        raise ValueError('CREATION_AGENT_THINKING 必须为空、enabled或disabled')
    return {'base_url': base_url, 'api_key': key, 'model': model, 'pricing': pricing,
            'pricing_source': source, 'thinking': thinking or None,
            'run_id': value('CREATION_AGENT_EVALUATION_RUN_ID') or 'initial'}, ledger, output


class EvaluationSpendLedger:
    """Persist reservations before requests; retain unknown charges and stop."""

    def __init__(self, path: Path, pricing: dict, limit_cny: Decimal = Decimal('10')):
        if not limit_cny.is_finite() or not Decimal('0') < limit_cny <= Decimal('10'):
            raise ValueError('真实验收累计预算必须大于0且不超过10元')
        if pricing.get('type') != 'text' or pricing.get('currency') != 'CNY':
            raise ValueError('必须先核实人民币文本计价')
        for key in ('input_price_per_1m', 'output_price_per_1m'):
            value = Decimal(str(pricing.get(key, 'NaN')))
            if not value.is_finite() or value <= 0:
                raise ValueError('必须先核实有效的输入/输出单价')
        cache_price = pricing.get('cache_input_price_per_1m')
        if cache_price not in (None, ''):
            value = Decimal(str(cache_price))
            if not value.is_finite() or value <= 0:
                raise ValueError('缓存输入单价必须是有效正数')
        self.path, self.pricing, self.limit = path, pricing, limit_cny
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _update(self, action):
        # Exclusive lock covers independent pytest processes and crash-safe append.
        import fcntl
        with self.path.open('a+', encoding='utf-8') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            file.seek(0)
            rows = [json.loads(line) for line in file if line.strip()]
            event, result = action(rows)
            file.seek(0, 2)
            file.write(json.dumps(event, ensure_ascii=False) + '\n')
            file.flush()
            import os
            os.fsync(file.fileno())
            return result

    def reserve(self, input_ceiling: int, output_ceiling: int) -> str:
        amount = compute_text_cost({'input_tokens': input_ceiling, 'output_tokens': output_ceiling}, self.pricing)
        def action(rows):
            latest = {row['id']: row for row in rows}
            if any(row['status'] != 'settled' for row in latest.values()):
                raise ValueError('存在用量未结清的验收请求，先核对供应商账单；不会继续消费')
            spent = sum((Decimal(row['cost_cny']) for row in latest.values()), Decimal('0'))
            if spent + amount > self.limit:
                raise ValueError('剩余10元累计预算不足以预留下一次调用，已停止真实验收')
            id = uuid4().hex
            return {'id': id, 'status': 'reserved', 'cost_cny': str(amount), 'input_ceiling': input_ceiling,
                    'output_ceiling': output_ceiling}, id
        return self._update(action)

    def settle(self, id: str, usage, completed: bool, error: BaseException | None = None):
        def action(rows):
            previous = next(row for row in reversed(rows) if row['id'] == id)
            if previous['status'] != 'reserved':
                raise ValueError('该请求已结算，禁止重复计入')
            # A interrupted stream may only report partial usage: preserve its reservation.
            known = completed and usage is not None and usage.input_tokens > 0
            over = known and (usage.input_tokens > previous['input_ceiling'] or usage.output_tokens > previous['output_ceiling'])
            cost = compute_text_cost(dataclasses.asdict(usage), self.pricing) if known else Decimal(previous['cost_cny'])
            return {**previous, 'status': 'estimate_exceeded' if over else 'settled' if known else 'unknown',
                    'cost_cny': str(cost), 'usage': dataclasses.asdict(usage) if usage is not None else None,
                    'error_type': type(error).__name__ if error else None,
                    'provider_status': getattr(error, 'status_code', None) if error else None}, None
        self._update(action)


class BudgetedEvaluationModel(WrapperModel):
    """Reserve a conservative request estimate before the provider sees a call."""

    def __init__(self, model, ledger: EvaluationSpendLedger):
        super().__init__(model)
        self.ledger = ledger

    def _reserve(self, messages, settings, parameters):
        max_output = (settings or {}).get('max_tokens')
        if not max_output or max_output <= 0:
            raise ValueError('真实评测必须显式限制单次输出token')
        # UTF-8 bytes conservatively bound byte-tokenized text, with framing allowance.
        # This is a preflight estimate, not a provider billing guarantee. Any excess
        # or missing usage closes the ledger for further calls pending reconciliation.
        input_bytes = len(ModelMessagesTypeAdapter.dump_json(messages))
        input_bytes += len(json.dumps(dataclasses.asdict(parameters), ensure_ascii=False, default=str).encode())
        return self.ledger.reserve(input_bytes + 4096, max_output)

    async def request(self, messages, model_settings, model_request_parameters):
        id = self._reserve(messages, model_settings, model_request_parameters)
        response = None
        error = None
        try:
            response = await self.wrapped.request(messages, model_settings, model_request_parameters)
            return response
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.ledger.settle(id, response.usage if response else None, response is not None, error)

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        id = self._reserve(messages, model_settings, model_request_parameters)
        response = None
        completed = False
        error = None
        try:
            async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as response:
                yield response
            completed = True
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.ledger.settle(id, response.usage() if response else None, completed, error)
