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


async def submit_analysis(novel_id, body, ctx, *, recheck_id=None):
    spec = body.model_dump(mode='json')
    existing = await StoryCommit.get_or_none(novel_id=novel_id, request_id=body.request_id)
    if existing:
        if existing.request_spec != spec:
            conflict('同一请求标识不能用于不同的故事分析')
        return await AiTask.get(id=existing.task_id)
    params = await workflow(novel_id, ctx, body.assistant_model_config_id, body.skill_id)
    params.update(operation='story_memory_analyze', output_contract=contract('extract'),
        creative_method=method(params['creative_method'], 'extract', params['prompt_language']))
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
                if waiting and waiting.chapter_id == body.chapter_id and waiting.status in {'draft', 'ready', 'needs_review'}:
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


async def submit_review(novel_id, commit_id, body, ctx):
    return await submit_candidate_task(novel_id, commit_id, body, ctx, repair=False)


async def submit_repair(novel_id, commit_id, body, ctx):
    return await submit_candidate_task(novel_id, commit_id, body, ctx, repair=True)


async def submit_candidate_task(novel_id, commit_id, body, ctx, *, repair):
    operation = 'story_memory_repair' if repair else 'story_memory_review'
    async with project_write(novel_id):
        commit = await get_commit(novel_id, commit_id)
        allowed = {'needs_review'} if repair else {'draft', 'needs_review', 'ready'}
        if commit.status not in allowed or commit.revision != body.expected_revision:
            conflict('候选已变化或已结束，请重新读取')
        if repair and commit.package_hash != body.expected_package_hash:
            conflict('确认对应的候选或审核已变化，请重新核对')
        await verify_inputs(commit)
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.project_analysis, status__in=ACTIVE_TASK_STATUSES):
            p = task.request_params
            if p.get('story_commit_id') == commit.id and p.get('story_revision') == commit.revision:
                if p.get('operation') == operation:
                    return task
                conflict('已有任务正在处理此候选，请等待完成')
        model_id = body.assistant_model_config_id
        if repair and model_id is None:
            original = await AiTask.get_or_none(id=commit.task_id)
            model_id = original.request_params.get('assistant_model_config_id') if original else None
        params = await workflow(novel_id, ctx, model_id)
        if repair:
            params.update(story_package_hash=commit.package_hash,
                creative_method=method(params['creative_method'], 'repair', params['prompt_language']))
        return await ai_task_executor.submit(AiTaskTypeEnum.project_analysis, {**params,
            **({'chapter_id': commit.chapter_id} if commit.chapter_id else {}),
            'operation': operation, 'story_commit_id': commit.id,
            'story_revision': commit.revision, 'output_contract': contract('repair' if repair else 'review')})
