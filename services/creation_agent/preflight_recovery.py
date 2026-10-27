"""Reconcile old model receipts only when durable checkpoints prove no request began."""

from datetime import datetime, timezone
from uuid import uuid5

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from models.usage_record import ModelUsageRecord
from services.creation_objects import project_write
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.messages import localized_message


async def reconcile_unstarted_model_task(task: AiTask) -> bool:
    if task.request_params.get('workflow_version') != 'agent-skills-v1':
        return False
    async with project_write(task.request_params['novel_id']) as connection:
        task = await AiTask.filter(id=task.id).using_db(connection).select_for_update().get()
        if task.status == TaskStatusEnum.failed and task.stage == 'failed':
            return await AgentOperation.filter(task=task, key='reconcile:unstarted_model', state='completed').using_db(connection).exists()
        if task.status != TaskStatusEnum.failed or task.stage != 'needs_review' or task.response_data:
            return False
        external = await AgentOperation.filter(task=task, external=True).using_db(connection).select_for_update()
        if not external or any(row.state != 'uncertain' or not row.key.startswith('model:') for row in external):
            return False
        parent_message = await AgentMessage.get_or_none(task=task, role='assistant').using_db(connection)
        if parent_message is None:
            return False
        steps = []
        for row in external:
            child = await AiTask.get_or_none(id=uuid5(task.id, row.key)).using_db(connection)
            if (child is None or child.task_type != AiTaskTypeEnum.creation_agent
                    or child.status != TaskStatusEnum.failed or child.response_data
                    or child.request_params.get('parent_task_id') != str(task.id)):
                return False
            message = await AgentMessage.get_or_none(task=child, role='assistant').using_db(connection)
            if (message is None or message.conversation_id != parent_message.conversation_id
                    or message.run_input.get('internal_production_step') is not True or message.native_messages):
                return False
            usage = message.usage or {}
            # RecordedAgentModel checkpoints in_progress before calling the provider.
            # Missing child/message evidence is unsafe; an existing empty checkpoint is provably local.
            if any(usage.get(key) for key in ('calls', 'requests', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')):
                return False
            if await ModelUsageRecord.filter(ai_task_id=child.id).using_db(connection).exists():
                return False
            steps.append({'operation_key': row.key, 'child_task_id': str(child.id),
                          'message_id': message.id, 'previous_state': row.state,
                          'evidence': 'no_model_request_checkpoint'})
        await AgentOperation.create(task=task, key='reconcile:unstarted_model', state='completed', using_db=connection,
            result={'previous_stage': task.stage, 'previous_error': task.error_message,
                    'steps': steps, 'reconciled_at': datetime.now(timezone.utc).isoformat()})
        await AgentOperation.filter(id__in=[row.id for row in external]).using_db(connection).update(state='failed')
        task.stage = 'failed'
        task.error_message = localized_message('本次模型请求未发出，请重新发起分析',
            _language=task.request_params.get('prompt_language', 'en'))
        await task.save(using_db=connection, update_fields=['stage', 'error_message', 'updated_at'])
        return True
