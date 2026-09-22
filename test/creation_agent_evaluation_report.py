"""Summarize saved synthetic evidence; never infer human quality scores."""

import hashlib
import json
import math
import statistics
import sys
from decimal import Decimal
from pathlib import Path

from test.creation_agent_evaluation import CORPUS_PATH, load_cases


def distribution(values):
    numbers = sorted(value for value in values if value is not None)
    return {'count': len(numbers), 'median': statistics.median(numbers) if numbers else None,
            'p95': numbers[max(0, math.ceil(len(numbers) * .95) - 1)] if numbers else None}


def summarize(records: list[dict], spend_events: list[dict] | None = None) -> dict:
    cases = {case.id: case for case in load_cases()}
    expected = {(id, repetition) for id in cases for repetition in (1, 2, 3)}
    seen = [(row['case_id'], row['repetition']) for row in records]
    steps = [step for row in records for step in row['steps']]
    errors = []
    if set(seen) != expected:
        errors.append('Fixed 90-instance corpus is incomplete or includes unexpected instances')
    if len(seen) != len(set(seen)):
        errors.append('Repeated attempts exist; all attempts retained, no best-result selection')
    corpus_hash = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    if any(row['corpus_sha256'] != corpus_hash for row in records):
        errors.append('Corpus versions differ')
    if len({row['model'] for row in records}) != 1:
        errors.append('Expected a single frozen model')
    if len({json.dumps({key: row.get(key) for key in ('provider_host', 'model_parameters', 'runtime_versions', 'pricing')}, sort_keys=True) for row in records}) != 1:
        errors.append('Provider, model parameters, runtime versions or pricing differ')
    if any(len(row['steps']) != len(cases[row['case_id']].steps) for row in records if row['case_id'] in cases):
        errors.append('A conversation sequence is incomplete')
    if any(step['hard_failures'] for step in steps):
        errors.append('Hard checks failed; inspect individual evidence')
    missing_cost = sum(step.get('cost_cny') is None for step in steps)
    if missing_cost:
        errors.append('Some provider usage/cost remains unknown')
    total = sum((Decimal(step['cost_cny']) for step in steps if step.get('cost_cny') is not None), Decimal('0'))
    if total > 10:
        errors.append('Reported total cost exceeds the authorized 10 CNY budget')
    ledger_total = None
    reserved_cost_total = Decimal('0')
    if spend_events is None:
        errors.append('Cumulative spend ledger, including smoke calls, has not been checked')
    else:
        latest = {row['id']: row for row in spend_events}
        ledger_total = sum((Decimal(row['cost_cny']) for row in latest.values()), Decimal('0'))
        reserved_cost_total = sum((Decimal(row['cost_cny']) for row in latest.values()
                                  if row.get('cost_basis') == 'user_authorized_full_reservation'), Decimal('0'))
        if any(row['status'] != 'settled' for row in latest.values()):
            errors.append('Spend ledger has unsettled or unverified usage')
        if ledger_total > 10 or ledger_total < total:
            errors.append('Cumulative ledger exceeds budget or does not cover recorded evaluations')
    scores = {key: [] for key in ('intent', 'continuity', 'independent_use')}
    reviewed = 0
    for step in steps:
        review = step.get('quality_review') or {}
        if not review.get('reviewer') or not review.get('reason'):
            continue
        if not isinstance(review.get('intent_fulfilled'), bool):
            continue
        if not all(isinstance(review.get(key), int) and not isinstance(review[key], bool) and 1 <= review[key] <= 5 for key in scores):
            continue
        reviewed += 1
        for key in scores:
            scores[key].append(review[key])
    if reviewed != len(steps) or not steps:
        errors.append('Independent quality review is incomplete')
    means = {key: statistics.mean(values) if values else None for key, values in scores.items()}
    if any(value is not None and value < 4 for value in means.values()) or any(1 in values for values in scores.values()):
        errors.append('Quality scores do not meet the fixed thresholds')
    executable = []
    for record in records:
        case = cases.get(record['case_id'])
        if case:
            executable.extend(step for planned, step in zip(case.steps, record['steps']) if planned.expected_outcome == 'edit')
    structural_success = sum(not step['hard_failures'] and not step['outcome_failures'] for step in executable)
    successful = sum(not step['hard_failures'] and not step['outcome_failures'] and
                     step['quality_review'].get('intent_fulfilled') is True for step in executable)
    if not executable or successful / len(executable) < .95:
        errors.append('Executable requests have not reached 95% reviewed success')
    return {'status': 'incomplete_or_failed' if errors else 'ready_for_final_review', 'reasons': errors,
            'planned_instances': 90, 'recorded_attempts': len(records), 'unique_instances': len(set(seen)),
            'executable_steps': len(executable), 'structurally_successful_steps': structural_success,
            'structural_success_rate': structural_success / len(executable) if executable else None,
            'reviewed_success_rate': successful / len(executable) if executable else None,
            'quality_reviewed_steps': reviewed, 'quality_means': means,
            'reported_cost_cny': str(total), 'unknown_cost_steps': missing_cost,
            'cumulative_spend_cny': str(ledger_total) if ledger_total is not None else None,
            'authorized_reservation_cny': str(reserved_cost_total),
            'requests': sum(step['usage'].get('requests', 0) for step in steps),
            'input_tokens': sum(step['usage'].get('input_tokens', 0) for step in steps),
            'output_tokens': sum(step['usage'].get('output_tokens', 0) for step in steps),
            'cache_read_tokens': sum(call.get('usage', {}).get('cache_read_tokens', 0) for step in steps for call in step['usage'].get('calls', [])),
            'recorded_retry_prompts': sum(step.get('retry_prompts') or 0 for step in steps),
            'unknown_retry_steps': sum(step.get('retry_prompts') is None for step in steps),
            'first_event_seconds': distribution([step.get('first_event_seconds') for step in steps]),
            'first_output_seconds': distribution([step.get('first_output_seconds') for step in steps]),
            'duration_seconds': distribution([step.get('duration_seconds') for step in steps]),
            'cost_per_step_cny': distribution([float(step['cost_cny']) if step.get('cost_cny') is not None else None for step in steps])}


if __name__ == '__main__':
    path = Path(sys.argv[1])
    ledger = path.with_name('spend.jsonl')
    result = summarize([json.loads(line) for line in path.read_text().splitlines() if line.strip()],
                       [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
