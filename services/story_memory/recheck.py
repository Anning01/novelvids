"""Durable sequential rechecks pause at each explicit chapter decision."""

from uuid import UUID, uuid5
from datetime import datetime, timezone

from fastapi import HTTPException
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.chapter import Chapter
from models.story_memory import StoryCommit
from schemas.story_memory import StoryAnalysisRequest
from services.ai_task_executor import ai_task_executor
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.waiting import WaitingForDependencies, WaitingForStoryConfirmation
from services.creation_agent.skill_stream import SkillRunActivity
from services.creation_objects import project_write, ACTIVE_TASK_STATUSES
from services.story_memory.sources import conflict, predecessor, source_snapshot
from services.story_memory.status import memory_status
from services.story_memory.store import commit_data, get_commit
from utils.enums import AiTaskTypeEnum


async def obsolete(task):
    for step in task.request_params['story_recheck_sources']:
        try:
            source = await source_snapshot(task.request_params['novel_id'], step['chapter_id'])
        except HTTPException:
            return True
        if fingerprint(source) != step['hash']:
            return True
    waiting_id = (task.response_data or {}).get('waiting_commit_id')
    if waiting_id:
        commit = await StoryCommit.get_or_none(id=waiting_id, novel_id=task.request_params['novel_id'])
        return commit is None or commit.status == 'stale'
    return False


async def submit_recheck(novel_id, body, ctx):
    from controllers.story_memory import workflow
    spec = body.model_dump(mode='json')
    # Use the existing task admission receipt, without adding another job table.
    params = await workflow(novel_id, ctx, body.assistant_model_config_id, body.skill_id)
    params.update(operation='story_memory_recheck', story_recheck_request=spec,
        submission_id=str(body.request_id), submission_hash=fingerprint(['story_memory_recheck', novel_id, spec]))
    from services.creation_agent.submissions import previous_submission
    existing = await previous_submission(AiTaskTypeEnum.project_analysis.value, params)
    if existing:
        return existing
    async with project_write(novel_id):
        existing = await previous_submission(AiTaskTypeEnum.project_analysis.value, params)
        if existing:
            return existing
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.project_analysis, status__in=ACTIVE_TASK_STATUSES):
            if task.request_params.get('operation') == 'story_memory_recheck' and task.request_params.get('novel_id') == novel_id:
                if not await obsolete(task):
                    conflict('已有故事复核任务，请先完成确认或停止原任务')
                from services.task_cancellation import cancel_task
                await cancel_task(task.id)
        chapters = await Chapter.filter(novel_id=novel_id).order_by('number', 'id')
        if body.from_chapter_id is not None:
            start = next((chapter for chapter in chapters if chapter.id == body.from_chapter_id), None)
            if start is None:
                raise HTTPException(404, '复核起点不属于当前作品')
            await predecessor(novel_id, start.id)
            chapters = [chapter for chapter in chapters if chapter.number >= start.number]
        targets = ([None] if body.from_chapter_id is None else []) + [chapter.id for chapter in chapters]
        params['story_recheck_sources'] = [
            {'chapter_id': identifier, 'hash': fingerprint(await source_snapshot(novel_id, identifier))}
            for identifier in targets]
        return await ai_task_executor.submit(AiTaskTypeEnum.project_analysis, params)


async def run_recheck(params):
    from controllers.story_memory import submit_analysis
    from services.creation_agent.handler import authorize_run
    execution = current_execution.get()
    await execution.before_request()
    ctx = await authorize_run(params)
    steps = params['story_recheck_sources']
    # A saved run cannot silently expand to a different edition while awaiting approval.
    for step in steps:
        if fingerprint(await source_snapshot(params['novel_id'], step['chapter_id'])) != step['hash']:
            conflict('复核期间剧本或项目设定再次变化，请按新版本重新发起复核；已确认记录仍保留')
    completed = []
    activity = SkillRunActivity(execution.message, params['task_id'])
    for step in steps:
        await execution.before_request()
        await AiTask.filter(id=params['task_id'], status=2).update(stage='rechecking_story',
            progress=int(100 * len(completed) / max(1, len(steps))),
            response_data={'state': 'rechecking', 'completed': completed, 'total': len(steps)})
        states = await memory_status(params['novel_id'])
        state = next(item for item in [states['baseline'], *states['chapters']] if item['chapter_id'] == step['chapter_id'])
        if state['state'] == 'current':
            completed.append({'chapter_id': step['chapter_id'], 'commit_id': state['commit_id'], 'state': 'current'})
            continue
        key = 'submit:story-recheck:' + str(step['chapter_id'])
        receipt = await AgentOperation.get_or_none(task_id=params['task_id'], key=key, state='completed')
        if receipt:
            commit = await get_commit(params['novel_id'], receipt.result['commit_id'])
            child = await AiTask.get(id=receipt.result['task_id'])
        else:
            request = StoryAnalysisRequest(request_id=uuid5(UUID(params['task_id']), key),
                chapter_id=step['chapter_id'], assistant_model_config_id=params['assistant_model_config_id'],
                skill_id=params['story_recheck_request']['skill_id'])
            # Do not inherit the parent's HTTP admission key for its distinct child request.
            from services.creation_agent.submissions import submission
            token = submission.set(None)
            try:
                async with project_write(params['novel_id']):
                    child = await submit_analysis(params['novel_id'], request, ctx, recheck_id=params['task_id'])
                    commit = await StoryCommit.get(task_id=child.id)
                    await AgentOperation.get_or_create(task_id=params['task_id'], key=key, defaults={
                        'state': 'completed', 'result': {'task_id': str(child.id), 'commit_id': commit.id}})
            finally:
                submission.reset(token)
        if child.status in {1, 6}:
            await ai_task_executor.run(child)
            await child.refresh_from_db()
            commit = await get_commit(params['novel_id'], commit.id)
        if child.status in ACTIVE_TASK_STATUSES:
            raise WaitingForDependencies()
        if commit.status == 'stale':
            conflict('待确认的故事候选已经失效，请按新版本重新发起复核')
        if commit.status == 'rejected':
            conflict('本章故事记忆已退回，后续复核已停止；请修改候选或重新分析后再发起复核')
        if commit.status == 'accepted':
            if not (await commit_data(commit, detail=False))['current']:
                conflict('已确认的前置记忆再次变化，请重新发起复核')
            completed.append({'chapter_id': step['chapter_id'], 'commit_id': commit.id, 'state': 'accepted'})
            continue
        if not commit.candidate:
            conflict('本章分析未完成，请重新发起复核；已有历史与前章提交仍保留')
        result = {'state': 'awaiting_confirmation', 'completed': completed,
            'waiting_commit_id': commit.id, 'waiting_task_id': str(child.id), 'total': len(steps)}
        await AiTask.filter(id=params['task_id'], status=2).update(progress=int(100 * len(completed) / max(1, len(steps))))
        now = datetime.now(timezone.utc).isoformat()
        number = (commit.source_snapshot.get('chapter') or {}).get('number')
        await activity.publish({'id': f'story-confirmation:{commit.id}', 'kind': 'status',
            'label': f'第 {number} 章记忆待确认' if number else '全局故事底稿待确认',
            'status': 'completed', 'started_at': now, 'finished_at': now})
        raise WaitingForStoryConfirmation(result)
    async with project_write(params['novel_id']):
        task = await AiTask.get(id=params['task_id'])
        if await obsolete(task):
            conflict('复核结束前源文本再次变化，请按新版本重新发起复核')
        states = await memory_status(params['novel_id'])
        by_chapter = {item['chapter_id']: item for item in [states['baseline'], *states['chapters']]}
        if any(by_chapter[step['chapter_id']]['state'] != 'current' for step in steps):
            conflict('复核结束前故事记忆再次变化，请重新发起复核')
    return {'state': 'completed', 'completed': completed, 'total': len(steps)}


async def resume_recheck(commit):
    """Called after the chapter decision commits; recovery can also run the queued job."""
    task = await AiTask.get_or_none(id=commit.task_id)
    parent_id = task.request_params.get('story_recheck_id') if task else None
    if parent_id is None:
        return None
    parent = await AiTask.get_or_none(id=parent_id)
    if parent is None or parent.request_params.get('novel_id') != commit.novel_id or parent.request_params.get('operation') != 'story_memory_recheck':
        return None
    async with project_write(commit.novel_id):
        parent = await AiTask.get(id=parent_id)
        if (parent.response_data or {}).get('waiting_commit_id') != commit.id:
            return None
        # A duplicate decision never requeues a running or completed batch.
        changed = await AiTask.filter(id=parent_id, status=2, stage='needs_review').update(status=6, stage='resuming')
    return await AiTask.get(id=parent_id) if changed else None
