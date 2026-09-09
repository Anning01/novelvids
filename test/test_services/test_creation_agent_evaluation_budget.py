import json
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from test.creation_agent_evaluation_budget import EvaluationSpendLedger, BudgetedEvaluationModel

PRICING = {'type': 'text', 'currency': 'CNY', 'input_price_per_1m': 10, 'output_price_per_1m': 10}


def test_ledger_survives_reruns_and_prevents_exceeding_total_budget(tmp_path):
    path = tmp_path / 'spend.jsonl'
    ledger = EvaluationSpendLedger(path, PRICING)
    id = ledger.reserve(400000, 400000)
    ledger.settle(id, RequestUsage(input_tokens=400000, output_tokens=400000), True)
    resumed = EvaluationSpendLedger(path, PRICING)
    with pytest.raises(ValueError, match='预算不足'):
        resumed.reserve(200000, 200000)
    assert len(path.read_text().splitlines()) == 2


@pytest.mark.parametrize('completed,usage', [(False, RequestUsage(input_tokens=1, output_tokens=1)), (True, None)])
def test_unknown_or_partial_usage_retains_reservation_and_blocks_more_calls(tmp_path, completed, usage):
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', PRICING)
    id = ledger.reserve(1000, 1000)
    ledger.settle(id, usage, completed)
    with pytest.raises(ValueError, match='未结清'):
        ledger.reserve(1, 1)
    row = json.loads(ledger.path.read_text().splitlines()[-1])
    assert row['status'] == 'unknown' and Decimal(row['cost_cny']) == Decimal('0.02')


def test_pending_request_after_crash_is_not_assumed_free(tmp_path):
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', PRICING)
    ledger.reserve(1000, 1000)
    with pytest.raises(ValueError, match='未结清'):
        EvaluationSpendLedger(ledger.path, PRICING).reserve(1, 1)


def test_provider_failure_records_safe_diagnostics_without_response_text(tmp_path):
    from pydantic_ai.exceptions import ModelHTTPError
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', PRICING)
    reservation = ledger.reserve(1000, 1000)
    ledger.settle(reservation, None, False, ModelHTTPError(429, 'synthetic', body='do-not-log-sensitive-response'))
    entry = json.loads(ledger.path.read_text().splitlines()[-1])
    assert entry['error_type'] == 'ModelHTTPError' and entry['provider_status'] == 429
    assert entry['status'] == 'unknown' and entry['cost_cny'] == '0.020000'
    assert 'do-not-log-sensitive-response' not in ledger.path.read_text()


@pytest.mark.parametrize('limit', ['0', '10.01', 'NaN'])
def test_budget_cannot_be_silently_raised(tmp_path, limit):
    with pytest.raises(ValueError):
        EvaluationSpendLedger(tmp_path / 'spend.jsonl', PRICING, Decimal(limit))


@pytest.mark.asyncio
async def test_wrapper_refuses_before_provider_call_when_price_exceeds_budget(tmp_path):
    calls = []
    def model(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[TextPart('不应调用')])
    pricing = {**PRICING, 'input_price_per_1m': 1000000}
    wrapped = BudgetedEvaluationModel(FunctionModel(model), EvaluationSpendLedger(tmp_path / 'spend.jsonl', pricing))
    with pytest.raises(ValueError, match='预算不足'):
        await wrapped.request([], {'max_tokens': 100}, ModelRequestParameters())
    assert not calls


def test_usage_above_estimate_is_recorded_and_closes_the_ledger(tmp_path):
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', PRICING)
    id = ledger.reserve(100, 100)
    ledger.settle(id, RequestUsage(input_tokens=200, output_tokens=100), True)
    assert json.loads(ledger.path.read_text().splitlines()[-1])['status'] == 'estimate_exceeded'
    with pytest.raises(ValueError, match='未结清'):
        ledger.reserve(10, 10)


def test_settled_evaluation_charge_uses_reported_cache_tokens(tmp_path):
    pricing = {**PRICING, 'input_price_per_1m': 4.5, 'cache_input_price_per_1m': 0.15,
               'output_price_per_1m': 13.5}
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', pricing)
    id = ledger.reserve(3000, 100)
    ledger.settle(id, RequestUsage(input_tokens=3000, cache_read_tokens=2700, output_tokens=100), True)
    entry = json.loads(ledger.path.read_text().splitlines()[-1])
    assert entry['status'] == 'settled'
    assert entry['cost_cny'] == '0.003105'


def test_configured_credentials_without_verified_pricing_do_not_authorize_a_call(monkeypatch):
    from test.creation_agent_evaluation_budget import real_evaluation_configuration
    for suffix in ('INPUT_PRICE_CNY_PER_1M', 'OUTPUT_PRICE_CNY_PER_1M', 'PRICE_SOURCE'):
        monkeypatch.delenv(f'CREATION_AGENT_{suffix}', raising=False)
    with pytest.raises(ValueError, match='核实人民币'):
        real_evaluation_configuration({'CREATION_AGENT_BASE_URL': 'https://example.invalid',
            'CREATION_AGENT_API_KEY': 'synthetic-key', 'CREATION_AGENT_MODEL': 'test-model'})
