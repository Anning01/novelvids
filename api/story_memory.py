"""Project-scoped candidate, review, decision and immutable history endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from auth.deps import AuthContext, require_team_access, require_roles
from controllers.story_memory import submit_analysis, submit_review
from models.story_memory import StoryCommit, StoryFact, StorySubject
from models.ai_task import AiTask
from schemas.ai_task import AiTaskOut
from schemas.story_memory import StoryAnalysisRequest, StoryCandidateUpdate, StoryDecision, StoryReviewRequest, StoryRecheckRequest
from services.ai_task_executor import ai_task_executor
from services.story_memory.store import commit_data, decide, get_commit, save_candidate
from utils.response_format import ResponseSchema

router = APIRouter(prefix='/novel/{novel_id}/story-memory', dependencies=[Depends(require_team_access)])
_EDITOR = Depends(require_roles('admin', 'creator'))


@router.get('/status', response_model=ResponseSchema)
async def status(novel_id: int):
    from services.story_memory.status import memory_status
    return ResponseSchema(data=await memory_status(novel_id))


@router.get('/context', response_model=ResponseSchema)
async def context(novel_id: int, chapter_id: int | None = Query(None, gt=0)):
    from services.story_memory.context import story_context
    return ResponseSchema(data=await story_context(novel_id, chapter_id))


@router.get('/activity', response_model=ResponseSchema)
async def activity(novel_id: int):
    active = await AiTask.filter(task_type=5, status__in=[1, 2, 6]).order_by('-created_at')
    task = next((task for task in active if task.request_params.get('novel_id') == novel_id
        and task.request_params.get('operation') in {'story_memory_recheck', 'story_memory_analyze', 'story_memory_review'}), None)
    if task is None:
        commit = await StoryCommit.filter(novel_id=novel_id).order_by('-id').first()
        identifier = (commit.review.get('task_id') or commit.task_id) if commit else None
        task = await AiTask.get_or_none(id=identifier) if identifier else None
        if task and task.request_params.get('story_recheck_id'):
            task = await AiTask.get(id=task.request_params['story_recheck_id'])
    return ResponseSchema(data=AiTaskOut.model_validate(task).model_dump(include={
        'id', 'status', 'stage', 'progress', 'response_data', 'error_message', 'started_at', 'finished_at'}) if task else None)


@router.post('/recheck', response_model=ResponseSchema[AiTaskOut])
async def recheck(novel_id: int, body: StoryRecheckRequest, bg: BackgroundTasks, ctx: AuthContext = _EDITOR):
    from services.story_memory.recheck import submit_recheck
    task = await submit_recheck(novel_id, body, ctx)
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.post('/analyze', response_model=ResponseSchema[AiTaskOut])
async def analyze(novel_id: int, body: StoryAnalysisRequest, bg: BackgroundTasks, ctx: AuthContext = _EDITOR):
    task = await submit_analysis(novel_id, body, ctx)
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.get('/commits', response_model=ResponseSchema)
async def history(novel_id: int, before_id: int | None = Query(None, gt=0), limit: int = Query(30, ge=1, le=100)):
    query = StoryCommit.filter(novel_id=novel_id)
    if before_id:
        query = query.filter(id__lt=before_id)
    commits = await query.order_by('-id').limit(limit)
    return ResponseSchema(data=[await commit_data(commit, detail=False) for commit in commits])


@router.get('/commits/{commit_id}', response_model=ResponseSchema)
async def detail(novel_id: int, commit_id: int):
    return ResponseSchema(data=await commit_data(await get_commit(novel_id, commit_id)))


@router.put('/commits/{commit_id}/candidate', response_model=ResponseSchema)
async def edit(novel_id: int, commit_id: int, body: StoryCandidateUpdate, _: AuthContext = _EDITOR):
    commit = await save_candidate(novel_id, commit_id, body.candidate, body.expected_revision)
    return ResponseSchema(data=await commit_data(commit))


@router.post('/commits/{commit_id}/review', response_model=ResponseSchema[AiTaskOut])
async def review(novel_id: int, commit_id: int, body: StoryReviewRequest, bg: BackgroundTasks, ctx: AuthContext = _EDITOR):
    task = await submit_review(novel_id, commit_id, body, ctx)
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.post('/commits/{commit_id}/decision', response_model=ResponseSchema)
async def decision(novel_id: int, commit_id: int, body: StoryDecision, bg: BackgroundTasks, ctx: AuthContext = _EDITOR):
    commit = await decide(novel_id, commit_id, body, ctx.user.id if ctx.user else None)
    from services.story_memory.recheck import resume_recheck
    continuation = await resume_recheck(commit)
    if continuation:
        bg.add_task(ai_task_executor.run, continuation)
    return ResponseSchema(data=await commit_data(commit))


@router.get('/subjects', response_model=ResponseSchema)
async def subjects(novel_id: int, after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return ResponseSchema(data=await StorySubject.filter(novel_id=novel_id, id__gt=after_id).order_by('id').limit(limit).values('id', 'kind', 'name', 'aliases'))


@router.get('/commits/{commit_id}/facts', response_model=ResponseSchema)
async def facts(novel_id: int, commit_id: int, after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    await get_commit(novel_id, commit_id)
    return ResponseSchema(data=await StoryFact.filter(novel_id=novel_id, commit_id=commit_id, id__gt=after_id)
        .order_by('id').limit(limit).values('id', 'subject_id', 'category', 'nature', 'content', 'scope', 'evidence', 'operation', 'replaces_id'))
