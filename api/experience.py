"""Real small-clip sessions and published works; no sample generation responses."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from auth.deps import AuthContext, get_auth_context, require_roles
from controllers import portfolio
from models.novel import Novel
from models.portfolio import PortfolioWork
from schemas.experience import ExperienceGenerateIn, ExperienceQuoteIn
from services.experience_quote import ClipQuote, clip_quote
from services.experience import CLIP_AUTHOR, clip_session, create_clip, start_clip
from services.ai_task_executor import ai_task_executor
from services.creation_agent.sessions import ACTIVE_STATUSES
from controllers.creation_agent import creation_agent_controller
from utils.response_format import ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles('admin', 'creator'))


@router.post('/quote', response_model=ResponseSchema[ClipQuote], summary='计算片段预计费用与可用额度，不创建任务')
async def quote(payload: ExperienceQuoteIn, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await clip_quote(payload, ctx))


@router.post('/generate', summary='创建单次片段创作上下文')
async def experience_generate(payload: ExperienceGenerateIn, ctx: AuthContext = Depends(get_auth_context), _: AuthContext = _EDITOR):
    return ResponseSchema(data=await create_clip(payload, ctx))


@router.get('/sessions', summary='我的最近片段')
async def sessions(ctx: AuthContext = Depends(get_auth_context)):
    rows = await Novel.filter(author=CLIP_AUTHOR, team_id=ctx.team_id,
        created_by=ctx.user.id if ctx.user else None).order_by('-updated_at').limit(20)
    return ResponseSchema(data=[{'project_id': row.id, 'name': row.name,
        'aspect_ratio': row.aspect_ratio, 'created_at': row.created_at} for row in rows])


@router.get('/sessions/{project_id}', summary='恢复片段创作')
async def session(project_id: int, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await clip_session(project_id, ctx))


@router.post('/sessions/{project_id}/start', summary='执行片段首次创作，重复请求复用同一任务')
async def start(project_id: int, background_tasks: BackgroundTasks, request: Request, ctx: AuthContext = Depends(get_auth_context), _: AuthContext = _EDITOR):
    task = await start_clip(project_id, ctx, media_base_url=str(request.base_url).rstrip("/"))
    if task.status in ACTIVE_STATUSES:
        background_tasks.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=await creation_agent_controller.snapshot(task.id, ctx))


@router.post('/save-to-library', summary='旧版样本转存接口已停用')
async def legacy_save():
    raise HTTPException(410, '请从真实生成结果中保存素材，旧版样本转存已停用')


@router.get('/showcase', summary='真实已公开作品')
async def get_showcase():
    records = await PortfolioWork.filter(status='public').order_by('-featured', 'featured_order', '-updated_at').limit(12)
    works = []
    for record in records:
        try:
            work = await portfolio.detail(record.novel_id)
        except HTTPException as error:
            if error.status_code == 404:
                continue
            raise
        if not work.episodes:
            continue
        preview = next((episode.version for episode in work.episodes if episode.version.id == work.cover_export_id), work.episodes[0].version)
        works.append({'id': f'work-{record.id}', 'title': work.title,
            'cover': f'/api/portfolio/public/{record.novel_id}/episodes/{preview.id}/cover',
            'video_url': f'/api/portfolio/public/{record.novel_id}/episodes/{preview.id}/video',
            'episodes_count': work.episode_count, 'duration': f'{int(preview.duration) // 60:02}:{int(preview.duration) % 60:02}' if preview.duration is not None else '', 'heat': '',
            'cover_width': preview.width, 'cover_height': preview.height,
            'category': work.category, 'tags': work.tags, 'description': work.description,
            'author': work.producer, 'novel_id': record.novel_id})
    return ResponseSchema(data=works)
