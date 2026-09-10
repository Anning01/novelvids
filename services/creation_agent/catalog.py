"""Bounded project discovery without loading every prompt into model context."""

from functools import partial
import json

from pypika_tortoise.functions import Cast
from tortoise.expressions import Function, Q

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.scene import Scene
from schemas.creation_objects import CreationObjectQuery
from services.creation_objects import CreationObjects
from services.creation_agent.context import chapter_context


class _JsonText(Function):
    """Portable text search over aliases on SQLite and PostgreSQL."""
    database_func = partial(Cast, as_type='TEXT')


class CreationCatalog:
    def __init__(self, novel_id: int, chapter_id: int | None):
        self.novel_id = novel_id
        self.chapter_id = chapter_id
        self.objects = CreationObjects(novel_id)

    async def read_chapter(self, chapter_id: int, character_budget: int, offset: int | None = None) -> dict:
        chapter = await self.objects.chapter(chapter_id)
        return chapter_context(chapter, character_budget, offset)

    async def chapter_asset_ids(self, chapter: Chapter) -> list[int]:
        rows = await Asset.filter(novel_id=self.novel_id).values('id', 'source_chapters', 'is_global')
        ids = {row['id'] for row in rows if row['is_global'] or chapter.number in (row['source_chapters'] or [])}
        ids.update(await Asset.filter(scenes__chapter_id=chapter.id, scenes__deleted_at__isnull=True).values_list('id', flat=True))
        return sorted(ids)

    async def search(self, request: CreationObjectQuery) -> dict:
        chapter_id = request.chapter_id or (self.chapter_id if request.scope == 'chapter' else None)
        chapter = await self.objects.chapter(chapter_id) if chapter_id else None
        if request.scope == 'chapter' and chapter is None:
            raise ValueError('当前没有章节；请先查询项目章节，再指定需要的章节')
        assets = Asset.filter(novel_id=self.novel_id, asset_type__in=[1, 2, 3])
        variants = AssetVariant.filter(asset__novel_id=self.novel_id, asset__deleted_at__isnull=True,
                                      asset__asset_type__in=[1, 2, 3])
        scenes = Scene.filter(chapter__novel_id=self.novel_id)
        chapters = Chapter.filter(novel_id=self.novel_id)
        if chapter:
            ids = await self.chapter_asset_ids(chapter)
            assets = assets.filter(id__in=ids)
            variants = variants.filter(asset_id__in=ids)
            scenes = scenes.filter(chapter_id=chapter.id)
            chapters = chapters.filter(id=chapter.id)
        if request.asset_type:
            assets = assets.filter(asset_type=request.asset_type)
            variants = variants.filter(asset__asset_type=request.asset_type)
        if request.search:
            term = request.search
            # Historical SQLite JSON uses escaped Chinese characters; PostgreSQL
            # JSONB may return literal Unicode when cast to text. Match both forms.
            encoded_term = json.dumps(term, ensure_ascii=True)[1:-1]
            assets = assets.annotate(alias_text=_JsonText('aliases')).filter(
                Q(canonical_name__icontains=term) | Q(description__icontains=term)
                | Q(alias_text__icontains=term) | Q(alias_text__icontains=encoded_term))
            variants = variants.filter(Q(name__icontains=term) | Q(description__icontains=term) | Q(asset__canonical_name__icontains=term))
            scenes = scenes.filter(description__icontains=term)
            chapters = chapters.filter(name__icontains=term)
        queries = [('chapter', chapters.order_by('number', 'id')), ('scene', scenes.order_by('chapter__number', 'sequence', 'id')),
                   ('asset', assets.order_by('canonical_name', 'id')), ('variant', variants.order_by('asset_id', 'id'))]
        if request.kind != 'all':
            queries = [(kind, query) for kind, query in queries if kind == request.kind]
        elif request.asset_type:
            queries = [(kind, query) for kind, query in queries if kind in {'asset', 'variant'}]
        counts = [(kind, query, await query.count()) for kind, query in queries]
        total = sum(count for _, _, count in counts)
        offset = (request.page - 1) * request.page_size
        items = []
        for kind, query, count in counts:
            if offset >= count:
                offset -= count
                continue
            if len(items) >= request.page_size:
                break
            query = query.offset(offset).limit(request.page_size - len(items))
            offset = 0
            if kind == 'chapter':
                rows = await query.values('id', 'number', 'name')
                items.extend({'kind': kind, 'id': row['id'], 'name': f"第{row['number']}章 · {row['name']}", 'chapter_id': row['id']} for row in rows)
            elif kind == 'scene':
                rows = await query.values('id', 'sequence', 'chapter_id', 'description', 'duration')
                items.extend({'kind': kind, **row, 'description': (row['description'] or '')[:240],
                              'name': f"分镜{row['sequence']} · {(row['description'] or '未命名')[:80]}"} for row in rows)
            elif kind == 'asset':
                rows = await query.values('id', 'canonical_name', 'asset_type', 'source_chapters', 'description')
                items.extend({'kind': kind, 'id': row['id'], 'name': row['canonical_name'], 'asset_type': row['asset_type'],
                    'chapters': row['source_chapters'], 'description': (row['description'] or '')[:240]} for row in rows)
            else:
                rows = await query.values('id', 'name', 'asset_id', 'chapter_numbers', 'description')
                items.extend({'kind': kind, 'id': row['id'], 'name': row['name'], 'asset_id': row['asset_id'],
                    'chapters': row['chapter_numbers'], 'description': (row['description'] or '')[:240]} for row in rows)
        for item in items:
            kind, object_id = item['kind'], item['id']
            if kind == 'chapter':
                item['reference_count'] = await Scene.filter(chapter_id=object_id).count()
            else:
                item['reference_count'] = (await self.references(kind, object_id, page_size=1))['total']
        return {'items': items, 'total': total, 'page': request.page,
                'next_page': request.page + 1 if request.page * request.page_size < total else None,
                'chapter_id': chapter_id, 'read_only': True}

    async def references(self, kind: str, object_id: int, *, page: int = 1, page_size: int = 20) -> dict:
        target = await self.objects.get(kind, object_id)
        if not 1 <= page_size <= 30 or page < 1:
            raise ValueError('引用分页参数无效')
        if kind == 'scene':
            query = Asset.filter(scenes__id=target.id, novel_id=self.novel_id).order_by('id')
            count = await query.count()
            rows = await query.offset((page - 1) * page_size).limit(page_size).values('id', 'canonical_name', 'asset_type')
            items = [{'kind': 'asset', 'id': row['id'], 'name': row['canonical_name'], 'asset_type': row['asset_type']} for row in rows]
        else:
            query = Scene.filter(chapter__novel_id=self.novel_id, assets__id=target.asset_id if kind == 'variant' else target.id)
            if kind == 'variant':
                query = query.filter(id__in=[scene.id for scene in await self.objects.variant_references(target)])
            count = await query.count()
            rows = await query.order_by('chapter__number', 'sequence').offset((page - 1) * page_size).limit(page_size).values('id', 'chapter_id', 'sequence', 'description')
            items = [{'kind': 'scene', 'id': row['id'], 'chapter_id': row['chapter_id'], 'name': f"分镜{row['sequence']} · {(row['description'] or '')[:80]}"} for row in rows]
        return {'items': items, 'total': count, 'next_page': page + 1 if page * page_size < count else None}
