"""Reuse only source-matched, saved, protocol-valid chapter extraction results."""

from dataclasses import asdict, dataclass

from models.agent_operation import AgentOperation
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import CreationConstraint
from models.chapter import Chapter
from models.novel import Novel
from services.extraction.cast import ChapterCast, cast_segment
from services.extraction.context import ExtractionContextLoader, normalize_source_chapters
from services.extraction.extractor import AssetExtractionResult, validate_required_design_assets


@dataclass
class ReusableExtraction:
    accepted: AssetExtractionResult
    required_assets: tuple[tuple[int, str], ...]
    required_variants: tuple[tuple[int, str, str], ...]
    summary: dict
    complete: bool
    repair_asset_ids: frozenset[int]
    repair_variant_ids: frozenset[int]
    repair_versions: dict[str, str]


class ExtractionReuse:
    async def targeted(self, execution, cast: ChapterCast) -> ReusableExtraction:
        """Keep source-identified catalog designs even when this chapter lacks an association."""
        from services.creation_agent.object_state import object_version
        from services.extraction.extractor import Person, Scene, Item
        from utils.messages import localized_message
        project = await Novel.get(id=execution.params['novel_id'])
        groups = {'persons': [], 'scenes': [], 'items': []}
        required, repair_ids, versions = [], set(), {}
        for cast_field, field, kind, model in (
            ('characters', 'persons', 1, Person), ('scenes', 'scenes', 2, Scene), ('items', 'items', 3, Item)):
            for item in getattr(cast, cast_field):
                if item.presence == 'voice_only':
                    continue
                required.append((kind, item.name))
                asset = await Asset.get_or_none(id=item.existing_asset_id, novel_id=project.id, asset_type=kind) if item.existing_asset_id else None
                if not asset:
                    deleted = await Asset.with_deleted().filter(novel_id=project.id, asset_type=kind, deleted_at__not_isnull=True)
                    if any(item.name in [row.canonical_name, *(row.aliases or [])] for row in deleted):
                        raise ValueError(localized_message('本章已有设定已移除，请先恢复后再补全，避免重复调用'))
                    continue
                metadata = asset.metadata or {}
                label = '群像' if metadata.get('reference_layout') == 'group_portrait' else '动物' if metadata.get('gender') == '其他（动物）' else '人物'
                if not (asset.base_traits or '').strip() or metadata.get('analysis_source') == 'project_analysis':
                    repair_ids.add(asset.id)
                else:
                    groups[field].append(model(name=asset.canonical_name, aliases=asset.aliases or [],
                        description=asset.description or '', base_traits=asset.base_traits, **({'label': label} if kind == 1 else {})))
                versions[f'asset:{asset.id}'] = await object_version(asset)
        required = tuple(dict.fromkeys(required))
        accepted = AssetExtractionResult(**groups)
        complete = {(kind, item.name) for field, kind in [('persons', 1), ('scenes', 2), ('items', 3)]
                    for item in getattr(accepted, field)} == set(required)
        return ReusableExtraction(accepted, required, (), {}, complete, frozenset(repair_ids), frozenset(), versions)

    async def input_revision(self, execution, context, project) -> str:
        from services.creation_agent.memory import creation_memory
        from services.creation_agent.plan_sources import fingerprint
        chapter = await Chapter.get(id=context.chapter.id, novel_id=project.id)
        related = await Asset.filter(novel_id=project.id, id__in=[a.id for a in context.assets
            if chapter.number in a.source_chapters])
        constraints = await creation_memory.for_generation(chapter, related)
        return fingerprint({'chapter': asdict(context.chapter), 'project': asdict(context.novel),
            'settings': {key: getattr(project, key) for key in ('aspect_ratio', 'style_key', 'custom_style_prompt')},
            'language': execution.language, 'rules': {key: execution.snapshot.contents.get(key) for key in
                ('assets', 'image', 'asset_contract', 'asset_lifecycle')}, 'constraints': constraints})

    async def remember_inputs(self, execution, context, *, targeted: bool):
        from utils.messages import localized_message
        project = await Novel.get(id=execution.params['novel_id'])
        revision = await self.input_revision(execution, context, project)
        key = 'extraction:inputs' if targeted else f'extraction:inputs:{context.chapter.id}:{execution.snapshot.revision}'
        previous = await AgentOperation.get_or_none(task_id=execution.params['task_id'], key='extraction:inputs') if not targeted else None
        row, _ = await AgentOperation.get_or_create(task_id=execution.params['task_id'], key=key,
            defaults={'state': 'completed', 'result': previous.result if previous else {'revision': revision}})
        if row.result.get('revision') != revision:
            raise ValueError(localized_message('资产提取的原文或规则已变化，请重新提交'))

    async def find(self, execution, chapter_id: int) -> ReusableExtraction | None:
        context = await ExtractionContextLoader().load(novel_id=execution.params['novel_id'], chapter_id=chapter_id)
        segment = cast_segment(asdict(context.chapter), execution.language, execution.snapshot.revision)
        input_key = f'extraction:inputs:{chapter_id}:{execution.snapshot.revision}'
        # Legacy inventory receipts locate earlier tasks. Their contents do not determine asset coverage.
        receipts = await AgentOperation.filter(key__in=[input_key, f'model:structured:ChapterCast:{segment}'],
            state='completed', task__task_type=1, task__status=3).select_related('task').order_by('-id')
        project = await Novel.get(id=execution.params['novel_id'])
        revision = await self.input_revision(execution, context, project)
        for receipt in receipts:
            task = receipt.task
            if task.request_params.get('novel_id') != project.id or task.request_params.get('chapter_id') != chapter_id:
                continue
            # Historical receipts did not freeze project settings. A later project/rule edit cannot be assumed safe.
            inputs = receipt if receipt.key == input_key else await AgentOperation.get_or_none(
                task=task, key='extraction:inputs', state='completed')
            if inputs:
                if inputs.result.get('revision') != revision:
                    continue
            elif project.updated_at > task.created_at or await CreationConstraint.filter(novel_id=project.id, updated_at__gt=task.created_at).exists():
                continue
            saved = await AgentOperation.get_or_none(task=task, key='persist:assets', state='completed')
            candidate = await AgentOperation.get_or_none(task=task, key='candidate:assets:', state='completed')
            if saved is None or candidate is None or candidate.result.get('issues'):
                continue
            original = AssetExtractionResult.model_validate(candidate.result['accepted'])
            groups = {'persons': [], 'scenes': [], 'items': []}
            required = []
            variants = []
            summary = {'persons': [], 'scenes': [], 'items': [], 'asset_ids': [], 'variant_ids': []}
            complete = True
            repair_assets, repair_variants = set(), set()
            repair_versions = {}
            for field, kind in [('persons', 1), ('scenes', 2), ('items', 3)]:
                bindings = {row['name']: row for row in saved.result.get(field, []) if row.get('asset_id')}
                for item in getattr(original, field):
                    binding = bindings.get(item.name)
                    asset = await Asset.get_or_none(id=binding['asset_id'], novel_id=project.id, asset_type=kind) if binding else None
                    if not asset and binding and await Asset.with_deleted().filter(id=binding['asset_id'], novel_id=project.id, deleted_at__not_isnull=True).exists():
                        from utils.messages import localized_message
                        raise ValueError(localized_message('本章已有设定已移除，请先恢复后再补全，避免重复调用'))
                    name = asset.canonical_name if asset else item.name
                    required.append((kind, name))
                    variant = None
                    if item.variant:
                        variant = await AssetVariant.get_or_none(id=binding.get('variant_id'), asset_id=asset.id) if asset and binding.get('variant_id') else None
                        variants.append((kind, name, variant.name if variant else item.variant.name))
                        if not variant and binding and binding.get('variant_id') and await AssetVariant.with_deleted().filter(id=binding['variant_id'], deleted_at__not_isnull=True).exists():
                            from utils.messages import localized_message
                            raise ValueError(localized_message('本章已有设定已移除，请先恢复后再补全，避免重复调用'))
                    valid = bool(asset and (asset.base_traits or '').strip()
                        and (asset.metadata or {}).get('analysis_source') != 'project_analysis'
                        and context.chapter.number in normalize_source_chapters(asset.source_chapters))
                    if item.variant:
                        valid = valid and bool(variant and (variant.base_traits or '').strip()
                            and context.chapter.number in normalize_source_chapters(variant.chapter_numbers))
                    if asset and not (asset.base_traits or '').strip():
                        repair_assets.add(asset.id)
                    if variant and not (variant.base_traits or '').strip():
                        repair_variants.add(variant.id)
                    if not valid:
                        from services.creation_agent.object_state import object_version
                        if asset and asset.id in repair_assets:
                            repair_versions[f'asset:{asset.id}'] = await object_version(asset)
                        if variant and variant.id in repair_variants:
                            repair_versions[f'variant:{variant.id}'] = await object_version(variant)
                        complete = False
                        continue
                    current = item.model_copy(update={'name': name, 'aliases': asset.aliases, 'description': asset.description or '',
                        'base_traits': asset.base_traits, 'variant': item.variant.model_copy(update={'existing_variant_id': variant.id, 'name': variant.name, 'base_traits': variant.base_traits,
                            'description': variant.description or ''}) if variant else None})
                    groups[field].append(current)
                    summary[field].append({'name': name, 'action': 'reused', 'asset_id': asset.id,
                        **({'variant_id': variant.id} if variant else {})})
                    summary['asset_ids'].append(asset.id)
                    if variant:
                        summary['variant_ids'].append(variant.id)
            required.extend((a.asset_type, a.canonical_name) for a in context.required_design_assets)
            accepted = AssetExtractionResult(**groups)
            required = tuple(dict.fromkeys(required))
            try:
                validate_required_design_assets(accepted, required)
            except ValueError:
                complete = False
            summary['asset_ids'] = sorted(set(summary['asset_ids']))
            summary['variant_ids'] = sorted(set(summary['variant_ids']))
            return ReusableExtraction(accepted, required, tuple(variants), summary, complete, frozenset(repair_assets), frozenset(repair_variants), repair_versions)
        return None


extraction_reuse = ExtractionReuse()
