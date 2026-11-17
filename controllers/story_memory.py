"""Explicit story-memory tasks; existing production remains opt-in and unchanged."""

from models.ai_task import AiTask
from models.story_memory import StoryCommit
from prompts.story_memory import contract, method
from services.ai_task_executor import ai_task_executor
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.strict_text import prepare_text_workflow
from services.creation_objects import ACTIVE_TASK_STATUSES, project_write
from services.story_memory.sources import conflict, latest_commit, predecessor, source_snapshot, verify_inputs
from services.story_memory.store import get_commit
from utils.enums import AiTaskTypeEnum


async def workflow(novel_id, ctx, model_id, skill_id=None):
    return await prepare_text_workflow({'novel_id': novel_id, 'team_id': ctx.team_id,
        'user_id': ctx.user.id if ctx.user else None, 'assistant_model_config_id': model_id}, 'story', skill_id)


async def submit_analysis(novel_id, body, ctx):
    spec = body.model_dump(mode='json')
    existing = await StoryCommit.get_or_none(novel_id=novel_id, request_id=body.request_id)
    if existing:
        if existing.request_spec != spec:
            conflict('同一请求标识不能用于不同的故事分析')
        return await AiTask.get(id=existing.task_id)
    params = await workflow(novel_id, ctx, body.assistant_model_config_id, body.skill_id)
    params.update(operation='story_memory_analyze', output_contract=contract('extract'),
        creative_method=method(params['creative_method'], 'extract', params['prompt_language']))
    async with project_write(novel_id):
        existing = await StoryCommit.get_or_none(novel_id=novel_id, request_id=body.request_id)
        if existing:
            if existing.request_spec != spec:
                conflict('同一请求标识不能用于不同的故事分析')
            return await AiTask.get(id=existing.task_id)
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


async def submit_review(novel_id, commit_id, body, ctx):
    params = await workflow(novel_id, ctx, body.assistant_model_config_id)
    async with project_write(novel_id):
        commit = await get_commit(novel_id, commit_id)
        if commit.status not in {'draft', 'needs_review', 'ready'} or commit.revision != body.expected_revision:
            conflict('候选已变化或已结束，请重新读取')
        await verify_inputs(commit)
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.project_analysis, status__in=ACTIVE_TASK_STATUSES):
            p = task.request_params
            if p.get('story_commit_id') == commit.id and p.get('story_revision') == commit.revision:
                return task
        return await ai_task_executor.submit(AiTaskTypeEnum.project_analysis, {**params,
            **({'chapter_id': commit.chapter_id} if commit.chapter_id else {}),
            'operation': 'story_memory_review', 'story_commit_id': commit.id,
            'story_revision': commit.revision, 'output_contract': contract('review')})
