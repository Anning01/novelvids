"""Idempotent image accounting still processes evidence after a billing receipt completes."""

from dataclasses import asdict
from models.agent_operation import AgentOperation
from models.usage_record import ModelUsageRecord
from services.creation_agent.operation_receipts import record_once
from services.creation_agent.review_evidence import reconcile_evidence


async def settle_image(task, arguments, evidence):
    from services.billing.recorder import billing_recorder, _consume_team_balance

    async def record():
        await task.refresh_from_db()
        ledger = (
            await ModelUsageRecord.filter(ai_task_id=task.id, billing_type="image")
            .order_by("id")
            .first()
        )
        if ledger is None:
            ledger = await billing_recorder.record_image(**arguments)
            if ledger is None:
                raise RuntimeError("Media usage record could not be saved")
            if evidence:
                ledger.usage = {
                    **ledger.usage,
                    "provider_evidence": asdict(evidence),
                    "usage_known": evidence.quantity is not None,
                    "missing_usage": evidence.quantity is None,
                }
                await ledger.save(update_fields=["usage"])
            if evidence is None and task.stage in {"needs_review", "review_closed"}:
                certainty = task.request_params.get("review_certainty") or {
                    "missing_usage": True,
                    "submission_uncertain": True,
                }
                ledger.usage = {**ledger.usage, **certainty}
                await ledger.save(update_fields=["usage"])
            await _consume_team_balance(
                ledger,
                task.request_params.get("team_id"),
                user_id=task.request_params.get("user_id"),
            )
        await AgentOperation.filter(task_id=task.id, key="billing:media").update(
            result={"usage_record_id": ledger.id}
        )

    await record_once(task.id, "billing:media", record)
    receipt = await AgentOperation.get(task_id=task.id, key="billing:media")
    ledger = await ModelUsageRecord.get_or_none(
        id=receipt.result.get("usage_record_id")
    )
    if ledger is None:
        ledger = (
            await ModelUsageRecord.filter(ai_task_id=task.id, billing_type="image")
            .order_by("id")
            .first()
        )
    await reconcile_evidence(task.id, ledger, evidence)
