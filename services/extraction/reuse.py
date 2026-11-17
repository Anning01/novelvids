"""Reuse only source-matched, saved, protocol-valid chapter extraction results."""

from dataclasses import asdict, dataclass

from models.agent_operation import AgentOperation
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import CreationConstraint
from models.chapter import Chapter
from models.novel import Novel
from services.extraction.cast import cast_segment
from services.extraction.context import ExtractionContextLoader, normalize_source_chapters
from services.extraction.extractor import AssetExtractionResult, validate_required_design_assets


@dataclass
class ReusableExtraction:
    summary: dict
    complete: bool


class ExtractionReuse:
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
            summary = {'persons': [], 'scenes': [], 'items': [], 'asset_ids': [], 'variant_ids': []}
            complete = True
            for field, kind in [('persons', 1), ('scenes', 2), ('items', 3)]:
                rows = [row for row in saved.result.get(field, []) if row.get('asset_id')]
                # Legacy receipts have only IDs; newer ones also freeze the extracted form name.
                saved_variants = {variant.id: variant for variant in await AssetVariant.with_deleted().filter(
                    id__in=[row['variant_id'] for row in rows if row.get('variant_id')])}
                bindings = {(row['name'], row.get('variant_name') or (
                    saved_variants[row['variant_id']].name if row.get('variant_id') in saved_variants else '')): row
                    for row in rows}
                for item in getattr(original, field):
                    binding = bindings.get((item.name, item.variant.name if item.variant else ''))
                    asset = await Asset.get_or_none(id=binding['asset_id'], novel_id=project.id, asset_type=kind) if binding else None
                    if not asset and binding and await Asset.with_deleted().filter(id=binding['asset_id'], novel_id=project.id, deleted_at__not_isnull=True).exists():
                        from utils.messages import localized_message
                        raise ValueError(localized_message('本章已有设定已移除，请先恢复后再补全，避免重复调用'))
                    name = asset.canonical_name if asset else item.name
                    required.append((kind, name))
                    variant = None
                    if item.variant:
                        variant = await AssetVariant.get_or_none(id=binding.get('variant_id'), asset_id=asset.id) if asset and binding.get('variant_id') else None
                        if not variant and binding and binding.get('variant_id') and await AssetVariant.with_deleted().filter(id=binding['variant_id'], deleted_at__not_isnull=True).exists():
                            from utils.messages import localized_message
                            raise ValueError(localized_message('本章已有设定已移除，请先恢复后再补全，避免重复调用'))
                    valid = bool(asset and (asset.base_traits or '').strip()
                        and (asset.metadata or {}).get('analysis_source') != 'project_analysis'
                        and context.chapter.number in normalize_source_chapters(asset.source_chapters))
                    if item.variant:
                        valid = valid and bool(variant and (variant.base_traits or '').strip()
                            and context.chapter.number in normalize_source_chapters(variant.chapter_numbers))
                    if not valid:
                        complete = False
                        continue
                    current = item.model_copy(update={'name': name, 'aliases': asset.aliases, 'description': asset.description or '',
                        'base_traits': asset.base_traits, 'variant': item.variant.model_copy(update={'existing_variant_id': variant.id, 'name': variant.name, 'base_traits': variant.base_traits,
                            'description': variant.description or ''}) if variant else None})
                    groups[field].append(current)
                    summary[field].append({'name': name, 'action': 'reused', 'asset_id': asset.id,
                        **({'variant_id': variant.id, 'variant_name': variant.name} if variant else {})})
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
            return ReusableExtraction(summary, complete)
        return None


extraction_reuse = ExtractionReuse()
