"""Batch queries for immutable, successfully composed episode versions."""
from collections.abc import Iterable

from tortoise.expressions import RawSQL
from models.chapter_export import ChapterExport


async def completed_edit_rows(chapter_ids: Iterable[int], *, db=None, export_ids: Iterable[int] | None = None) -> list[dict]:
    query = ChapterExport.filter(
        chapter_id__in=list(chapter_ids), task__status=3,
        media_ref__isnull=False, collection_complete=True,
    ).using_db(db).exclude(media_ref='')
    if export_ids is not None:
        query = query.filter(id__in=list(export_ids))
    return await query.annotate(
        render_kind=RawSQL("recipe->>'kind'"),
        revision_value=RawSQL("CAST(recipe->>'revision' AS INTEGER)"),
    ).filter(render_kind='editor_render').order_by('-task__finished_at', '-id').values(
        'id', 'chapter_id', 'novel_id', 'output_probe', 'updated_at', 'revision_value',
        completed_at='task__finished_at',
    )
