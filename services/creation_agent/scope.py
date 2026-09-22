"""Frozen run scope, independent of the model's proposed tool arguments."""

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.scene import Scene
from schemas.creation_agent import AgentRunRequest
from services.creation_objects import CreationObjects


class CreationWriteScope:
    def __init__(self, novel_id: int, request: AgentRunRequest):
        self.novel_id = novel_id
        self.request = request.model_copy(deep=True)
        self.selected = frozenset((t.kind, t.id) for t in request.targets)

    def writable(self):
        if self.request.write_scope == 'read_only':
            raise ValueError('本轮为只读查询，不能写入')

    async def chapter(self, chapter_id: int | None):
        self.writable()
        chapter_id = chapter_id or self.request.chapter_id
        if chapter_id is None:
            raise ValueError('请先指定要操作的章节')
        chapter = await CreationObjects(self.novel_id).chapter(chapter_id)
        if self.request.write_scope != 'project' and chapter.id != self.request.chapter_id:
            raise ValueError('目标章节超出本轮授权范围')
        return chapter

    async def target(self, kind: str, target, *, new: bool = False):
        self.writable()
        if new:
            return
        if self.selected:
            if (kind, target.id) not in self.selected:
                raise ValueError('目标不在本轮指定的对象范围内')
            return
        if self.request.write_scope == 'selected':
            raise ValueError('本轮没有指定可修改对象')
        if self.request.write_scope == 'project':
            return
        chapter = await self.chapter(self.request.chapter_id)
        if isinstance(target, Scene):
            if target.chapter_id != chapter.id:
                raise ValueError('目标分镜不在本轮章节范围内')
        elif isinstance(target, Asset):
            belongs = chapter.number in (target.source_chapters or []) or await Scene.filter(
                chapter_id=chapter.id, assets__id=target.id).exists()
            if not belongs:
                raise ValueError('目标设定不在本轮章节范围内')
            other_uses = await Scene.filter(assets__id=target.id).exclude(chapter_id=chapter.id).exists()
            if target.is_global or other_uses or set(target.source_chapters or []) - {chapter.number}:
                raise ValueError('这是跨章共享设定；本章外观变化请创建或编辑本章形态。修改基础设定请明确指定该设定。')
        elif isinstance(target, AssetVariant):
            if chapter.number not in (target.chapter_numbers or []) or set(target.chapter_numbers or []) - {chapter.number}:
                raise ValueError('该形态适用范围超出本章；请指定该形态或使用本章形态')

    async def creation(self, *, kind: str, chapter_ids: list[int], parent_id: int | None = None, anchor_id: int | None = None):
        self.writable()
        for chapter_id in chapter_ids:
            await self.chapter(chapter_id)
        if self.selected or self.request.write_scope == 'selected':
            allowed = ('asset', parent_id) in self.selected if kind == 'variant' else ('scene', anchor_id) in self.selected if kind == 'scene' else False
            if not allowed:
                raise ValueError('新增对象超出指定对象范围；请使用本章范围，或为指定角色创建形态、在指定分镜后插入')
