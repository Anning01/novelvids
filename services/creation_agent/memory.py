"""Project-scoped creative constraints with source attribution and story-time selection."""

import hashlib

from tortoise.transactions import in_transaction

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentMessage, CreationConstraint, PromptChange
from models.scene import Scene
from models.novel import Novel
from schemas.creation_agent import AgentRunRequest, CreationConstraintProposal, CreationConstraintScope, PromptStatusRequest
from services.creation_agent.sessions import agent_sessions


class CreationMemory:
    async def for_generation(self, chapter: Chapter, assets: list[Asset]) -> list[dict]:
        """Carry chapter/project rules into new scenes, never old scene-only edits."""
        asset_names = {asset.id: asset.canonical_name for asset in assets}
        constraints = await CreationConstraint.filter(novel_id=chapter.novel_id, superseded_by_id=None).order_by('id')
        result = []
        for constraint in constraints:
            scope = CreationConstraintScope.model_validate(constraint.scope)
            if scope.asset_id and scope.asset_id not in asset_names:
                continue
            if (scope.kind == 'project'
                or scope.kind == 'chapter' and scope.chapter_id == chapter.id
                or scope.kind == 'range' and scope.start_chapter <= chapter.number <= scope.end_chapter):
                result.append({'content': constraint.content, 'scope': constraint.scope,
                               'asset_name': asset_names.get(scope.asset_id)})
        return result

    async def validate(self, source: AgentMessage, proposals: list[CreationConstraintProposal]) -> None:
        await source.fetch_related("conversation")
        novel_id = source.conversation.novel_id
        for proposal in proposals:
            fingerprint = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
            if await CreationConstraint.filter(source_message_id=source.id, fingerprint=fingerprint).exists():
                continue
            if proposal.source_quote not in source.content:
                raise ValueError("长期创作约束必须引用本轮用户明确表达的原文，不能把模型推断当成设定")
            scope = proposal.scope
            await agent_sessions.validate_scope(novel_id, AgentRunRequest(
                request_id=source.request_id, message=source.content, chapter_id=scope.chapter_id, targets=scope.targets))
            if scope.asset_id and not await Asset.filter(id=scope.asset_id, novel_id=novel_id).exists():
                raise ValueError("约束角色不属于当前项目")
            if scope.kind == "range":
                numbers = set(await Chapter.filter(novel_id=novel_id, number__in=[scope.start_chapter, scope.end_chapter]).values_list("number", flat=True))
                if numbers != {scope.start_chapter, scope.end_chapter}:
                    raise ValueError("剧情区间必须使用当前项目已有章节")
            if proposal.supersedes_id:
                previous = await CreationConstraint.get_or_none(id=proposal.supersedes_id, novel_id=novel_id, superseded_by_id=None)
                if previous is None or previous.scope != scope.model_dump():
                    raise ValueError("要替代的约束已变化或作用范围不同，请先澄清")

    async def save(self, source: AgentMessage, proposals: list[CreationConstraintProposal]) -> list[CreationConstraint]:
        await self.validate(source, proposals)
        async with in_transaction() as connection:
            await Novel.filter(id=source.conversation.novel_id).using_db(connection).select_for_update().first()
            saved = []
            for proposal in proposals:
                fingerprint = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
                constraint, created = await CreationConstraint.get_or_create(
                    source_message_id=source.id, fingerprint=fingerprint, using_db=connection,
                    defaults={"novel_id": source.conversation.novel_id, "content": proposal.content,
                              "source_quote": proposal.source_quote, "scope": proposal.scope.model_dump(),
                              "supersedes_id": proposal.supersedes_id})
                if not created:
                    saved.append(constraint)
                    continue
                if proposal.supersedes_id:
                    updated = await CreationConstraint.filter(id=proposal.supersedes_id, superseded_by_id=None).using_db(connection).update(superseded_by_id=constraint.id)
                    if not updated:
                        raise ValueError("约束已被其他会话修改，请重新读取后再保存")
                saved.append(constraint)
            return saved

    async def applicable(self, novel_id: int, request: AgentRunRequest | PromptStatusRequest) -> list[dict]:
        """Keep per-target scope explicit so a batch never propagates A-only rules to B."""
        scenes = await Scene.filter(id__in=[t.id for t in request.targets if t.kind == 'scene'], chapter__novel_id=novel_id).prefetch_related('chapter', 'assets')
        variants = await AssetVariant.filter(id__in=[t.id for t in request.targets if t.kind == 'variant'], asset__novel_id=novel_id)
        assets = await Asset.filter(id__in=[t.id for t in request.targets if t.kind == 'asset'], novel_id=novel_id)
        chapter = await Chapter.get_or_none(id=request.chapter_id, novel_id=novel_id) if request.chapter_id else None
        context = {}
        for target in request.targets:
            related_scene = next((scene for scene in scenes if target.kind == 'scene' and scene.id == target.id), None)
            related_variant = next((variant for variant in variants if target.kind == 'variant' and variant.id == target.id), None)
            related_asset = next((asset for asset in assets if target.kind == 'asset' and asset.id == target.id), None)
            if related_scene:
                chapters = [related_scene.chapter]
                asset_ids = {asset.id for asset in related_scene.assets}
            elif related_variant:
                from services.creation_objects import CreationObjects

                uses = await CreationObjects(novel_id).variant_references(related_variant)
                numbers = set(related_variant.chapter_numbers or []) | {scene.chapter.number for scene in uses}
                chapters = await Chapter.filter(novel_id=novel_id, number__in=numbers)
                asset_ids = {related_variant.asset_id}
            elif related_asset:
                uses = await Scene.filter(assets__id=related_asset.id).prefetch_related('chapter')
                numbers = set(related_asset.source_chapters or []) | {scene.chapter.number for scene in uses}
                query = Chapter.filter(novel_id=novel_id)
                chapters = await (query if related_asset.is_global else query.filter(number__in=numbers))
                asset_ids = {related_asset.id}
            else:
                chapters, asset_ids = [], set()
            context[(target.kind, target.id)] = (chapters, asset_ids)
        constraints = await CreationConstraint.filter(novel_id=novel_id, superseded_by_id=None).order_by('id')
        result = []
        for constraint in constraints:
            scope = CreationConstraintScope.model_validate(constraint.scope)
            applicable = []
            for target in request.targets:
                target_chapters, asset_ids = context[(target.kind, target.id)]
                if scope.asset_id and scope.asset_id not in asset_ids:
                    continue
                if (scope.kind == 'project'
                    or scope.kind == 'targets' and target in scope.targets
                    or scope.kind == 'chapter' and any(ch.id == scope.chapter_id for ch in target_chapters)
                    or scope.kind == 'range' and any(scope.start_chapter <= ch.number <= scope.end_chapter for ch in target_chapters)):
                    applicable.append(target.model_dump())
            if applicable or (not request.targets and not scope.asset_id and (scope.kind == 'project' or scope.kind == 'chapter' and chapter and chapter.id == scope.chapter_id
                or scope.kind == 'range' and chapter and scope.start_chapter <= chapter.number <= scope.end_chapter)):
                result.append({"id": constraint.id, "content": constraint.content, "scope": constraint.scope,
                               "applies_to": applicable, "version": constraint.updated_at.isoformat()})
        return result

    async def prompt_status(self, novel_id: int, request: PromptStatusRequest) -> list[dict]:
        """Report rules not used in the current prompt's latest recorded edit.

        A matching record proves the rule was available during editing, not that
        the model's creative interpretation is semantically correct.
        """
        rules = await self.applicable(novel_id, request)
        pending = {(target.kind, target.id): [rule for rule in rules if target.model_dump() in rule['applies_to']]
                   for target in request.targets}
        unresolved = {key for key, value in pending.items() if value}
        if unresolved:
            models = {'scene': Scene, 'asset': Asset, 'variant': AssetVariant}
            current = {}
            for kind, model in models.items():
                fields = ['id', 'prompt', 'prompt_params'] if kind == 'scene' else ['id', 'base_traits']
                for row in await model.filter(id__in=[id for target_kind, id in unresolved if target_kind == kind]).values(*fields):
                    current[(kind, row.pop('id'))] = row
            # Recorded rule IDs establish applicability; cross-table timestamp
            # comparisons are unnecessary and unreliable across SQLite offsets.
            query = PromptChange.filter(novel_id=novel_id, reverted_at=None).order_by('-id')
            offset = 0
            while unresolved:
                batch = await query.offset(offset).limit(100).only('changes')
                if not batch:
                    break
                for change in batch:
                    for item in change.changes:
                        key = (item['kind'], item['target_id'])
                        if key not in unresolved:
                            continue
                        # CRUD receipts also contain names, ordering and relation
                        # fields. Only a recorded prompt change establishes that
                        # the current prompt was checked against these rules.
                        prompt_after = {field: value for field, value in item['after'].items()
                                        if field in {'prompt', 'prompt_params', 'base_traits'}}
                        if not prompt_after:
                            continue
                        unresolved.remove(key)
                        if key in current and all(current[key].get(field) == value for field, value in prompt_after.items()):
                            pending[key] = [rule for rule in pending[key] if rule['id'] not in item.get('constraint_ids', [])]
                offset += len(batch)
        return [{**target.model_dump(), 'pending_constraints': [{'id': rule['id'], 'content': rule['content']}
                for rule in pending[(target.kind, target.id)]]} for target in request.targets]


creation_memory = CreationMemory()
