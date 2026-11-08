"""One durable repair allowance shared by a run and its production steps."""

import hashlib
import json

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from pydantic_ai.messages import ModelRequest, RetryPromptPart
from utils.messages import localized_message


class RepairExhausted(ValueError):
    error_code = 'CREATION_REPAIR_EXHAUSTED'


async def recovery_root(params):
    task_id = str(params['task_id'])
    visited = set()
    while task_id not in visited:
        visited.add(task_id)
        task = await AiTask.get_or_none(id=task_id)
        if task is None:
            break
        parent = (task.request_params or {}).get('recovery_root_task_id') or (task.request_params or {}).get('origin_run_id') or (task.request_params or {}).get('parent_task_id')
        if not parent:
            break
        task_id = str(parent)
    return task_id


def retry_issues(messages):
    """Only the newest request can authorize repair; old feedback is history."""
    if not messages or not isinstance(messages[-1], ModelRequest):
        return []
    issues = []
    for part in messages[-1].parts:
        if not isinstance(part, RetryPromptPart):
            continue
        if isinstance(part.content, list):
            issues.extend({'tool': part.tool_name, 'path': list(error.get('loc', ())),
                           'code': error.get('type', 'validation_error')}
                          for error in part.content)
        else:
            # Store a fingerprint, not object contents or provider payloads.
            code = 'json_invalid' if any(marker in part.content.lower() for marker in ('invalid json', 'json_invalid')) else 'tool_validation'
            issues.append({'tool': part.tool_name, 'code': code,
                           'detail_hash': hashlib.sha256(part.content.encode()).hexdigest()})
    return issues


async def claim_repair(task_id, issues):
    digest = hashlib.sha256(json.dumps(issues, sort_keys=True, default=str).encode()).hexdigest()
    row, _ = await AgentOperation.get_or_create(task_id=task_id, key='recovery:repair')
    claimed = await AgentOperation.filter(id=row.id, state='pending').update(
        state='completed', result={'fingerprint': digest, 'issues': issues})
    if not claimed:
        raise RepairExhausted(localized_message('本次任务的增量修复已用完，候选和调用记录已保留，请核对失败步骤。'))


async def failure_checkpoint(task_id, message_id, issues, *, stage='validation'):
    await AgentOperation.update_or_create(task_id=task_id, key='recovery:failure', defaults={
        'state': 'completed', 'result': {'message_id': message_id, 'stage': stage, 'issues': issues}})


async def recovery_summaries(tasks):
    """Batch history projection; raw arguments never leave the private journal."""
    from models.creation_agent import AgentMessage
    from tortoise.expressions import Q
    from fastapi import HTTPException
    from services.creation_agent.run_recovery import resume_source
    results = {str(task.id): None for task in tasks}
    if not tasks:
        return results
    owners = await AgentMessage.filter(task_id__in=list(results), role='assistant').select_related('conversation').only(
        'id', 'task_id', 'conversation_id', 'conversation__id', 'conversation__novel_id')
    messages = await AgentMessage.filter(conversation_id__in={owner.conversation_id for owner in owners},
        role='assistant').select_related('task').only('id', 'task_id', 'task__id', 'task__request_params').order_by('id')
    scopes = {}
    for task in tasks:
        ids = {str(task.id)}
        for message in messages:
            params = message.task.request_params or {}
            if params.get('parent_task_id') in ids or params.get('origin_run_id') == str(task.id):
                ids.add(str(message.task_id))
        scopes[str(task.id)] = ids
    relevant_ids = set().union(*scopes.values())
    operations = await AgentOperation.filter(task_id__in=relevant_ids).filter(
        Q(key='recovery:failure') | Q(key='recovery:repair') |
        Q(key__startswith='candidate:') | Q(key__startswith='draft:')).order_by('id')
    saved_responses = {str(identifier) for identifier in await AgentMessage.filter(
        task_id__in=relevant_ids, role='assistant').exclude(native_messages=[]).values_list('task_id', flat=True)}
    by_task = {}
    for row in operations:
        by_task.setdefault(str(row.task_id), []).append(row)
    for task in tasks:
        owner = next((owner for owner in owners if owner.task_id == task.id), None)
        if owner is None:
            continue
        ids = scopes[str(task.id)]
        rows = [row for identifier in ids for row in by_task.get(identifier, [])]
        failures = sorted((row for row in rows if row.key == 'recovery:failure'), key=lambda row: row.id)
        candidates = [row for row in rows if row.key.startswith(('candidate:', 'draft:')) and row.state == 'completed']
        if not failures and not candidates:
            continue
        can_resume = False
        if task.status == 4 and not any(row.key == 'recovery:repair' and row.state == 'completed' for row in rows):
            try:
                await resume_source(owner.conversation, task.id)
                can_resume = True
            except HTTPException:
                pass
        accepted = pending = 0
        for candidate in candidates:
            payload = candidate.result
            if candidate.key.startswith('candidate:assets:'):
                accepted += sum(len(items) for items in payload.get('accepted', {}).values() if isinstance(items, list))
                pending += len(payload.get('issues', []))
            elif candidate.key.startswith('draft:'):
                accepted += len(payload.get('changes', {}).get('operations', []))
            else:
                accepted += len(payload.get('accepted_shots', []))
                pending += len(payload.get('pending', {}))
        issues = failures[-1].result.get('issues', []) if failures else []
        results[str(task.id)] = {
            'failure_step': failures[-1].result.get('stage') if failures else None,
            'error_code': ('CREATION_OUTPUT_LIMIT' if any(issue.get('code') == 'output_length' for issue in issues) else
                           'CREATION_JSON_INVALID' if any(issue.get('code') == 'json_invalid' for issue in issues)
                           else 'CREATION_VALIDATION_FAILED') if failures and task.status == 4 else None,
            'reusable_count': accepted, 'pending_count': pending,
            'draft_id': max(candidate.id for candidate in candidates) if candidates else None,
            'can_resume': can_resume,
            'responses_saved': len(saved_responses & ids),
        }
    return results


async def recovery_summary(task):
    return (await recovery_summaries([task]))[str(task.id)]
