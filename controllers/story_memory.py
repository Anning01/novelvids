"""Explicit story-memory tasks; existing production remains opt-in and unchanged."""

from models.ai_task import AiTask
from models.story_memory import StoryCommit
from prompts.story_memory import contract, method
from services.ai_task_executor import ai_task_executor
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.strict_text import prepare_text_workflow
from services.creation_objects import ACTIVE_TASK_STATUSES, project_write
from services.story_memory.sources import conflict, latest_commit, predecessor, source_snapshot
from services.story_memory.store import CANDIDATE_STATUSES
from utils.enums import AiTaskTypeEnum


async def workflow(novel_id, ctx, model_id, skill_id=None):
    return await prepare_text_workflow({'novel_id': novel_id, 'team_id': ctx.team_id,
        'user_id': ctx.user.id if ctx.user else None, 'assistant_model_config_id': model_id}, 'story', skill_id)


async def submit_analysis(novel_id, body, ctx, *, recheck_id=None):
    spec = body.model_dump(mode='json')
    existing = await StoryCommit.get_or_none(novel_id=novel_id, request_id=body.request_id)
    if existing:
        if existing.request_spec != spec:
            conflict('同一请求标识不能用于不同的故事分析')
        return await AiTask.get(id=existing.task_id)
    params = await workflow(novel_id, ctx, body.assistant_model_config_id, body.skill_id)
    params.update(operation='story_memory_analyze', output_contract=contract(),
        creative_method=method(params['creative_method'], params['prompt_language']))
    if recheck_id is not None:
        params['story_recheck_id'] = str(recheck_id)
    async with project_write(novel_id):
        existing = await StoryCommit.get_or_none(novel_id=novel_id, request_id=body.request_id)
        if existing:
            if existing.request_spec != spec:
                conflict('同一请求标识不能用于不同的故事分析')
            return await AiTask.get(id=existing.task_id)
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.project_analysis, status__in=ACTIVE_TASK_STATUSES):
            request = task.request_params
            if request.get('novel_id') != novel_id:
                continue
            if request.get('operation') == 'story_memory_analyze' and request.get('chapter_id') == body.chapter_id:
                conflict('这一范围正在分析，请在创作助手查看进度')
            if not recheck_id and request.get('operation') == 'story_memory_recheck' and task.stage == 'needs_review':
                commit_id = (task.response_data or {}).get('waiting_commit_id')
                waiting = await StoryCommit.get_or_none(id=commit_id, novel_id=novel_id)
                if waiting and waiting.chapter_id == body.chapter_id and waiting.status in CANDIDATE_STATUSES:
                    conflict('这一范围已有待处理候选，请在创作助手查看候选')
        source = await source_snapshot(novel_id, body.chapter_id)
        parent_id = await predecessor(novel_id, body.chapter_id)
        previous = await latest_commit(novel_id, body.chapter_id)
        commit = await StoryCommit.create(novel_id=novel_id, chapter_id=body.chapter_id,
            request_id=body.request_id, request_spec=spec, source_snapshot=source, source_hash=fingerprint(source),
            parent_id=parent_id, replaces_id=previous.id if previous else None,
            created_by=ctx.user.id if ctx.user else None)
        task = await ai_task_executor.submit(AiTaskTypeEnum.project_analysis, {**params,
            **({'chapter_id': body.chapter_id} if body.chapter_id else {}),
            'story_commit_id': commit.id, 'story_revision': commit.revision})
        commit.task = task
        await commit.save(update_fields=['task_id', 'updated_at'])
        return task
