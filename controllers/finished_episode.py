"""Completed edits and version-specific publication."""
from typing import Literal

from fastapi import HTTPException

from auth.deps import AuthContext, auth_disabled, ensure_novel_access, require_roles, require_super_admin
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.novel import Novel
from models.portfolio import PortfolioWork
from schemas.finished_episode import FinishedEpisodeItem, FinishedEpisodeVersion
from services.creation_objects import project_write
from services.finished_episodes import completed_edit_rows
from utils.messages import localized_message as msg


def can_read_project(project: Novel, ctx: AuthContext) -> bool:
    return auth_disabled() or ctx.is_super_admin or (ctx.team_id is not None and ctx.team_id == project.team_id)


def can_publish_project(project: Novel, ctx: AuthContext) -> bool:
    return can_read_project(project, ctx) and (
        auth_disabled() or ctx.is_super_admin or bool(ctx.membership and ctx.membership.role == 'admin')
    )


def version_from_row(row: dict) -> FinishedEpisodeVersion:
    probe = row['output_probe'] or {}
    return FinishedEpisodeVersion(
        id=row['id'], revision=row['revision_value'],
        completed_at=row['completed_at'] or row['updated_at'],
        duration=probe.get('duration'), width=probe.get('width'), height=probe.get('height'), fps=probe.get('fps'),
    )


async def list_finished(ctx: AuthContext, scope: Literal['team', 'published', 'featured'],
                        project_id: int | None, page: int, page_size: int) -> dict:
    projects = Novel.all()
    if scope == 'team' and not auth_disabled() and not ctx.is_super_admin:
        projects = projects.filter(team_id=ctx.team_id) if ctx.team_id is not None else projects.filter(id__in=[])
    project_by_id = {project.id: project for project in await projects.only('id', 'team_id', 'name')}
    chapters = {chapter.id: chapter for chapter in await Chapter.filter(novel_id__in=list(project_by_id)).only('id', 'novel_id', 'number', 'name')}
    publications = {
        row.chapter_id: row for row in await FinishedEpisodePublication.filter(chapter_id__in=list(chapters), export_id__isnull=False)
    }
    managed_projects = set()
    if scope != 'team':
        managed_projects = set(await PortfolioWork.filter(novel_id__in=list(project_by_id)).values_list('novel_id', flat=True))
    target_ids = chapters if scope == 'team' else [
        key for key, row in publications.items()
        if chapters[key].novel_id not in managed_projects and (scope == 'published' or row.featured)
    ]
    selected = {}
    for row in await completed_edit_rows(target_ids):
        chapter = chapters[row['chapter_id']]
        if row['novel_id'] != chapter.novel_id:
            continue
        publication = publications.get(chapter.id)
        if scope != 'team' and (not publication or publication.export_id != row['id']):
            continue
        selected.setdefault(chapter.id, row)
    project_options = sorted(
        {row['novel_id']: {'id': row['novel_id'], 'name': project_by_id[row['novel_id']].name}
         for row in selected.values()}.values(), key=lambda project: project['name'],
    )
    chosen = [row for row in selected.values() if project_id is None or row['novel_id'] == project_id]
    offset = (page - 1) * page_size
    items = []
    for row in chosen[offset:offset + page_size]:
        chapter = chapters[row['chapter_id']]
        project = project_by_id[chapter.novel_id]
        publication = publications.get(chapter.id)
        items.append(describe_item(row, chapter, project, publication, ctx))

    return {'items': items, 'total': len(chosen), 'projects': project_options}



def describe_item(row, chapter, project, publication, ctx) -> FinishedEpisodeItem:
    return FinishedEpisodeItem(
        chapter_id=chapter.id, project_id=project.id, project_name=project.name,
        number=chapter.number, title=chapter.name, version=version_from_row(row),
        published_id=publication.export_id if publication else None,
        featured=bool(publication and publication.featured),
        can_publish=can_publish_project(project, ctx),
        can_feature=auth_disabled() or ctx.is_super_admin,
    )


async def chapter_item(chapter_id: int, ctx: AuthContext) -> FinishedEpisodeItem:
    chapter, project = await _chapter_project(chapter_id)
    owned = can_read_project(project, ctx)
    if not owned and await PortfolioWork.filter(novel_id=project.id).exists():
        raise HTTPException(404, msg('成片不存在'))
    publication = await FinishedEpisodePublication.get_or_none(chapter_id=chapter.id, export_id__isnull=False)
    for row in await completed_edit_rows([chapter.id]):
        if row['novel_id'] != project.id:
            continue
        if owned or publication and publication.export_id == row['id']:
            return describe_item(row, chapter, project, publication, ctx)
    raise HTTPException(404, msg('成片不存在'))

async def _chapter_project(chapter_id: int):
    chapter = await Chapter.get_or_none(id=chapter_id)
    project = await Novel.get_or_none(id=chapter.novel_id) if chapter else None
    if not chapter or not project:
        raise HTTPException(404, msg('成片不存在'))
    return chapter, project


async def versions(chapter_id: int, ctx: AuthContext) -> list[FinishedEpisodeVersion]:
    chapter, project = await _chapter_project(chapter_id)
    owned = can_read_project(project, ctx)
    if not owned and await PortfolioWork.filter(novel_id=project.id).exists():
        raise HTTPException(404, msg('成片不存在'))
    publication = await FinishedEpisodePublication.get_or_none(chapter_id=chapter_id)
    result = [
        version_from_row(row) for row in await completed_edit_rows([chapter.id])
        if row['novel_id'] == project.id and (owned or (publication and publication.export_id == row['id']))
    ]
    if not result and not owned:
        raise HTTPException(404, msg('成片不存在'))
    return result


async def accessible_export(export_id: int, ctx: AuthContext) -> ChapterExport:
    export = await ChapterExport.get_or_none(id=export_id, task__status=3, collection_complete=True).exclude(media_ref__isnull=True).exclude(media_ref='')
    if not export or export.recipe.get('kind') != 'editor_render':
        raise HTTPException(404, msg('成片不存在'))
    chapter, project = await _chapter_project(export.chapter_id)
    if chapter.novel_id != export.novel_id:
        raise HTTPException(404, msg('成片不存在'))
    if not can_read_project(project, ctx):
        managed = await PortfolioWork.filter(novel_id=project.id).exists()
        published = await FinishedEpisodePublication.filter(chapter_id=chapter.id, export_id=export.id).exists()
        if managed or not published:
            raise HTTPException(404, msg('成片不存在'))
    return export


async def publish(chapter_id: int, export_id: int | None, ctx: AuthContext, expected_id: int | None = None) -> None:
    await require_roles('admin')(ctx)
    chapter, project = await _chapter_project(chapter_id)
    await ensure_novel_access(project.id, ctx)
    if export_id is not None:
        export = await accessible_export(export_id, ctx)
        if export.chapter_id != chapter.id:
            raise HTTPException(404, msg('成片不存在'))
    async with project_write(project.id) as db:
        if await PortfolioWork.filter(novel_id=project.id).using_db(db).exists():
            raise HTTPException(409, msg('请在作品详情管理公开设置'))
        publication, _ = await FinishedEpisodePublication.get_or_create(chapter_id=chapter.id, using_db=db)
        if publication.export_id not in (expected_id, export_id):
            raise HTTPException(409, msg('发布状态已更新，请刷新后重试'))
        if publication.export_id != export_id:
            publication.export_id = export_id
            publication.featured = False
            await publication.save(using_db=db, update_fields=['export_id', 'featured', 'updated_at'])


async def feature(chapter_id: int, export_id: int, featured: bool, ctx: AuthContext) -> None:
    await require_super_admin(ctx)
    chapter, project = await _chapter_project(chapter_id)
    export = await accessible_export(export_id, ctx)
    if export.chapter_id != chapter.id:
        raise HTTPException(404, msg('成片不存在'))
    async with project_write(project.id) as db:
        if await PortfolioWork.filter(novel_id=project.id).using_db(db).exists():
            raise HTTPException(409, msg('请在作品详情管理公开设置'))
        changed = await FinishedEpisodePublication.filter(chapter_id=chapter.id, export_id=export_id).using_db(db).update(featured=featured)
        if not changed:
            raise HTTPException(409, msg('请先发布这个版本'))
