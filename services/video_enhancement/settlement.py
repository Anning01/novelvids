"""A single atomic receipt owns processing usage and its balance transaction."""

from dataclasses import asdict
from models.agent_operation import AgentOperation
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.creation_agent.operation_receipts import record_once
from services.video_enhancement.contract import MediaProbe, enhancement_cost, RESOLUTION_SHORT_SIDE
from utils.messages import localized_message


async def settle_enhancement(task, export) -> ModelUsageRecord | None:
    result = export.provider_result or {}
    if result.get('status') not in {'completed', 'failed'}:
        return None
    from services.billing.recorder import billing_recorder
    from services.balance import consume, accumulate_member_cost

    snapshot = task.request_params['config_snapshot']
    config = AiModelConfig(**snapshot)
    values = result.get('result') or {}
    known = result['status'] == 'failed'
    inconsistent = False
    cost = 0
    if result['status'] == 'completed':
        try:
            resolution = (export.recipe or {}).get('resolution', '1080p')
            if values.get('resolution') != resolution:
                raise ValueError('missing resolution')
            cost = enhancement_cost(values.get('duration'), RESOLUTION_SHORT_SIDE[resolution], values.get('fps'), config.pricing)
            from decimal import Decimal
            source = MediaProbe.model_validate(export.source_probe)
            tolerance = max(Decimal(2) / source.fps, Decimal('0.1'))
            inconsistent = (abs(Decimal(str(values['duration'])) - source.duration) > tolerance
                or abs(Decimal(str(values['fps'])) - source.fps) > Decimal('0.01'))
            if inconsistent:
                raise ValueError('Reported usage differs from the frozen source')
            known = True
        except ValueError:
            known = False
            cost = 0
    usage = {'seconds': values.get('duration'), 'fps': values.get('fps'), 'resolution': values.get('resolution'),
        'external_task_id': export.provider_task_id, 'export_id': export.id, 'usage_known': known,
        'missing_usage': not known, 'submission_outcome_known': True, 'submission_uncertain': not known,
        'accounting_needs_review': inconsistent,
        'pricing_basis': 'provider_report' if known else 'needs_review'}
    from services.creation_agent.review_evidence import MediaEvidence, reconcile_evidence, quantity
    evidence = MediaEvidence('media_processing', quantity=quantity(values.get('duration')) if known and values.get('duration') is not None else 0 if result['status']=='failed' else None,
        completed=result['status']=='completed', media_available=bool(export.media_ref), external_task_id=export.provider_task_id)
    usage['provider_evidence'] = asdict(evidence)

    async def record():
        existing = await ModelUsageRecord.get_or_none(ai_task_id=task.id, billing_type='media_processing')
        if existing is not None:
            return
        ledger = await billing_recorder._create(novel_id=export.novel_id, task_type=8,
            billing_type='media_processing', config=config, fallback_model=config.model,
            usage=usage, cost=cost, status=3 if result['status']=='completed' else 4,
            ai_task_id=task.id, team_id=task.request_params.get('team_id'), user_id=task.request_params.get('user_id'))
        if ledger is None:
            raise RuntimeError(localized_message('媒体处理用量暂未保存，等待结算恢复'))
        if ledger.team_id is not None:
            if ledger.cost_source != 'team_key':
                await consume(ledger.team_id, ledger.cost, usage_record_id=ledger.id, strict=True)
            await accumulate_member_cost(ledger.team_id, ledger.user_id, ledger.cost, strict=True)
        await AgentOperation.filter(task=task, key='billing:enhancement').update(result={'usage_record_id':ledger.id})

    await record_once(task.id, 'billing:enhancement', record)
    ledger = await ModelUsageRecord.get_or_none(ai_task_id=task.id, billing_type='media_processing')
    await reconcile_evidence(task.id, ledger, evidence)
    return ledger
