"""Archive grouped edits and control the public catalogue at the work boundary."""
from collections import defaultdict

from fastapi import HTTPException

from auth.deps import AuthContext, auth_disabled, require_roles
from controllers.billing import billing_scope
from controllers.finished_episode import can_publish_project, can_read_project, version_from_row
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.novel import Novel
from models.portfolio import PortfolioEpisode, PortfolioWork
from schemas.portfolio import WorkAction, WorkDetail, WorkEpisode, WorkFilter, WorkProfile, WorkSort, WorkSummary
from services.billing.aggregation import recorded_project_costs
from services.creation_objects import project_write
from services.finished_episodes import completed_edit_rows
from utils.messages import localized_message as msg
from prompts.styles import AUTO_STYLE_KEY, AUTO_STYLE_LABEL, get_style


async def _load(projects: list[Novel], *, public: bool = False) -> list[WorkDetail]:
    project_ids = [project.id for project in projects]
    archives = {work.novel_id: work for work in await PortfolioWork.filter(novel_id__in=project_ids)}
    if public:
        projects = [project for project in projects if project.id in archives and archives[project.id].status == 'public']
        project_ids = [project.id for project in projects]
    chapters = {
        chapter.id: chapter for chapter in
        await Chapter.filter(novel_id__in=project_ids).only('id', 'novel_id', 'number', 'name')
    }
    published = {
        (episode.work_id, episode.chapter_id): episode.export_id for episode in
        await PortfolioEpisode.filter(work_id__in=[archives[project_id].id for project_id in project_ids if project_id in archives])
    }
    by_project: dict[int, list[WorkEpisode]] = defaultdict(list)
    seen = set()
    for row in await completed_edit_rows(chapters):
        chapter = chapters[row['chapter_id']]
        if chapter.novel_id != row['novel_id'] or chapter.id in seen:
            continue
        archive = archives.get(chapter.novel_id)
        pinned = published.get((archive.id, chapter.id)) if archive and archive.status == 'public' else None
        if public and pinned != row['id']:
            continue
        seen.add(chapter.id)
        by_project[chapter.novel_id].append(WorkEpisode(
            chapter_id=chapter.id, number=chapter.number, title=chapter.name,
            version=version_from_row(row), published_id=pinned,
        ))

    producers = {}
    if not public and not auth_disabled():
        from auth.models import User
        user_ids = {project.created_by for project in projects} - {None}
        producers = {
            row.id: row.nickname or row.username for row in
            await User.filter(id__in=list(user_ids)).only('id', 'nickname', 'username')
        }
    results = []
    for project in projects:
        episodes = sorted(by_project[project.id], key=lambda episode: (episode.number, episode.chapter_id))
        if episodes:
            results.append(_describe(project, archives.get(project.id), episodes, producers, public=public))
    return results


def _work_category(project: Novel, archive: PortfolioWork | None) -> str:
    if project.custom_style_prompt and project.custom_style_prompt.strip():
        return '自定义风格'
    style = get_style(project.style_key)
    if style:
        return style.label
    if project.style_key == AUTO_STYLE_KEY:
        return AUTO_STYLE_LABEL
    return project.project_type or (archive.category if archive else '') or (
        '视频重制' if project.workflow_kind == 'remake' else '短剧'
    )


def _describe(project: Novel, archive: PortfolioWork | None, episodes: list[WorkEpisode],
              producers: dict[int, str], *, public: bool) -> WorkDetail:
    cover = next((episode for episode in episodes if archive and episode.chapter_id == archive.cover_chapter_id), episodes[0])
    durations = [episode.version.duration for episode in episodes]
    heights = {
        min(episode.version.width, episode.version.height) for episode in episodes
        if episode.version.width and episode.version.height
    }
    resolution = f'{next(iter(heights))}P' if len(heights) == 1 else 'mixed' if heights else ''
    first_saved = min(episode.version.completed_at for episode in episodes)
    latest_saved = max(episode.version.completed_at for episode in episodes)
    production_seconds = None
    if not public and project.created_at and latest_saved >= project.created_at:
        production_seconds = int((latest_saved - project.created_at).total_seconds())
    tags = archive.tags if archive else project.tags or []
    category = _work_category(project, archive)
    return WorkDetail(
        project_id=project.id, title=archive.title if archive else project.name,
        description=archive.description if archive else project.description or '',
        category=category,
        tags=[tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else [],
        status=archive.status if archive else 'private',
        featured=bool(archive and archive.status == 'public' and archive.featured),
        featured_order=archive.featured_order if archive else 0,
        episode_count=len(episodes), duration=sum(durations) if all(value is not None for value in durations) else None,
        resolution=resolution, cover_export_id=cover.version.id, cover_chapter_id=cover.chapter_id,
        producer=producers.get(project.created_by, ''), producer_id=None if public else project.created_by,
        production_seconds=production_seconds,
        archived_at=archive.created_at if archive else first_saved,
        updated_at=archive.updated_at if archive else latest_saved,
        last_action=archive.last_action if archive and not public else 'archive',
        revision=archive.revision if archive and not public else 0, episodes=episodes,
    )


def _summary(item: WorkDetail) -> dict:
    return item.model_dump(include=set(WorkSummary.model_fields))


async def _attach_costs(works: list[WorkDetail], ctx: AuthContext) -> None:
    if not works:
        return
    can_read_costs = auth_disabled() or ctx.is_super_admin or (
        ctx.membership and ctx.membership.role in ('admin', 'creator')
    )
    if not can_read_costs:
        return
    team_id, user_id = billing_scope(ctx)
    costs = await recorded_project_costs([work.project_id for work in works], team_id, user_id)
    for work in works:
        work.recorded_cost = costs.get(work.project_id, 0)
        work.cost_scope = 'self' if user_id is not None else 'project'


def _matches_status(work: WorkSummary, status: WorkFilter) -> bool:
    if status == 'featured':
        return work.featured
    if status == 'private':
        return work.status in ('private', 'withdrawn')
    return status in ('all', work.status)


async def list_works(ctx: AuthContext, *, status: WorkFilter, search: str, category: str,
                     producer_id: int | None, sort: WorkSort, project_id: int | None, page: int, page_size: int):
    projects = Novel.all()
    if not auth_disabled() and not ctx.is_super_admin:
        projects = projects.filter(team_id=ctx.team_id) if ctx.team_id is not None else projects.filter(id__in=[])
    columns = ('id', 'name', 'description', 'project_type', 'tags', 'created_by', 'team_id', 'created_at', 'style_key', 'custom_style_prompt', 'workflow_kind')
    works = await _load(await projects.only(*columns))
    counts = {
        'all': len(works),
        'pending': sum(work.status == 'pending' for work in works),
        'public': sum(work.status == 'public' for work in works),
        'private': sum(work.status in ('private', 'withdrawn') for work in works),
        'featured': sum(work.featured for work in works),
    }
    recent = sorted(works, key=lambda work: (work.updated_at, work.project_id), reverse=True)[:4]
    categories = sorted({work.category for work in works if work.category})
    producers = {work.producer_id: work.producer for work in works if work.producer and work.producer_id is not None}
    query = search.strip().casefold()
    filtered = [
        work for work in works
        if _matches_status(work, status)
        and (not query or query in work.title.casefold())
        and (not category or category == work.category)
        and (producer_id is None or producer_id == work.producer_id)
        and (project_id is None or project_id == work.project_id)
    ]
    if sort == 'title':
        filtered.sort(key=lambda work: (work.title.casefold(), work.project_id))
    elif sort == 'duration':
        filtered.sort(key=lambda work: (work.duration or 0, work.project_id), reverse=True)
    elif sort == 'recommended':
        filtered.sort(key=lambda work: (not work.featured, work.featured_order, -work.project_id))
    else:
        filtered.sort(key=lambda work: (work.archived_at, work.project_id), reverse=True)
    offset = (page - 1) * page_size
    visible = filtered[offset:offset + page_size]
    await _attach_costs(visible, ctx)
    return {
        'items': [_summary(work) for work in visible], 'total': len(filtered),
        'counts': counts, 'recent': [_summary(work) for work in recent],
        'categories': categories, 'producers': [{'id': key, 'name': name} for key, name in producers.items()],
        'archive_options': [{'id': work.project_id, 'name': work.title} for work in works if work.revision == 0],
    }


async def detail(project_id: int, ctx: AuthContext | None = None, *, include_costs: bool = False) -> WorkDetail:
    project = await Novel.get_or_none(id=project_id)
    if not project or (ctx is not None and not can_read_project(project, ctx)):
        raise HTTPException(404, msg('作品不存在'))
    works = await _load([project], public=ctx is None)
    if not works:
        raise HTTPException(404, msg('作品不存在'))
    work = works[0]
    if ctx is not None:
        work.can_manage = can_publish_project(project, ctx)
        work.can_edit = work.can_manage or bool(ctx.membership and ctx.membership.role == 'creator' and work.status != 'public')
        if include_costs:
            await _attach_costs([work], ctx)
    return work


async def _locked_archive(project: Novel, snapshot: WorkDetail, revision: int, db):
    archive = await PortfolioWork.get_or_none(novel_id=project.id).using_db(db)
    if revision != (archive.revision if archive else 0):
        raise HTTPException(409, msg('作品已更新，请刷新后重试'))
    if archive is None:
        archive = await PortfolioWork.create(
            novel_id=project.id, title=snapshot.title, description=snapshot.description,
            category=snapshot.category, tags=snapshot.tags, revision=0, using_db=db,
        )
    return archive


async def save_profile(project_id: int, payload: WorkProfile, ctx: AuthContext):
    await require_roles('creator', 'admin')(ctx)
    snapshot = await detail(project_id, ctx)
    if not snapshot.can_edit:
        raise HTTPException(403, msg('没有编辑作品的权限'))
    if payload.cover_chapter_id is not None and payload.cover_chapter_id not in {episode.chapter_id for episode in snapshot.episodes}:
        raise HTTPException(422, msg('请选择本作品的剧集封面'))
    async with project_write(project_id) as db:
        project = await Novel.get(id=project_id).using_db(db)
        if not can_read_project(project, ctx):
            raise HTTPException(404, msg('作品不存在'))
        archive = await _locked_archive(project, snapshot, payload.revision, db)
        if archive.status == 'public' and not can_publish_project(project, ctx):
            raise HTTPException(403, msg('没有编辑作品的权限'))
        archive.category = _work_category(project, archive)
        for key, value in payload.model_dump(exclude={'revision', 'category'}).items():
            setattr(archive, key, value)
        archive.last_action = 'edit' if archive.revision else 'archive'
        archive.revision += 1
        await archive.save(using_db=db)


async def change_status(project_id: int, payload: WorkAction, ctx: AuthContext):
    if payload.action == 'submit':
        await require_roles('creator', 'admin')(ctx)
    else:
        await require_roles('admin')(ctx)
    snapshot = await detail(project_id, ctx)
    async with project_write(project_id) as db:
        project = await Novel.get(id=project_id).using_db(db)
        if not can_read_project(project, ctx):
            raise HTTPException(404, msg('作品不存在'))
        archive = await _locked_archive(project, snapshot, payload.revision, db)
        action = payload.action
        if action == 'submit' and archive.status in ('private', 'withdrawn'):
            archive.status = 'pending'
        elif action == 'approve' and archive.status == 'pending':
            archive.status = 'private'
        elif action == 'publish':
            requested = set(payload.export_ids)
            if not requested or len(requested) != len(payload.export_ids):
                raise HTTPException(422, msg('请选择要公开的剧集'))
            chapter_ids = await Chapter.filter(novel_id=project_id).using_db(db).values_list('id', flat=True)
            rows = await completed_edit_rows(chapter_ids, db=db, export_ids=requested)
            rows = [row for row in rows if row['novel_id'] == project_id]
            if len(rows) != len(requested) or len({row['chapter_id'] for row in rows}) != len(rows):
                raise HTTPException(422, msg('每集只能公开一个已完成的版本'))
            await PortfolioEpisode.filter(work_id=archive.id).using_db(db).delete()
            await PortfolioEpisode.bulk_create([
                PortfolioEpisode(work_id=archive.id, chapter_id=row['chapter_id'], export_id=row['id'])
                for row in rows
            ], using_db=db)
            archive.status = 'public'
        elif action == 'withdraw' and archive.status == 'public':
            archive.status = 'withdrawn'
            archive.featured = False
        elif action == 'recommend' and archive.status == 'public':
            archive.featured = payload.featured
            archive.featured_order = payload.featured_order
        else:
            raise HTTPException(409, msg('当前作品状态不支持此操作'))
        archive.last_action = action
        archive.revision += 1
        await archive.save(using_db=db)


async def public_export(project_id: int, export_id: int) -> ChapterExport:
    episode = await PortfolioEpisode.get_or_none(
        work__novel_id=project_id, work__status='public', export_id=export_id,
        chapter__novel_id=project_id, export__novel_id=project_id,
        export__collection_complete=True, export__task__status=3,
    ).select_related('export')
    if not episode or episode.export.chapter_id != episode.chapter_id or not episode.export.media_ref or episode.export.recipe.get('kind') != 'editor_render':
        raise HTTPException(404, msg('作品不存在'))
    return episode.export
