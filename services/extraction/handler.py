from services.ai_task_executor import BaseTaskHandler
from services.extraction.context import ExtractionContextLoader
from services.extraction.messages import ExtractionMessageBuilder
from services.extraction.persistence import AssetUpsertService
from services.creation_agent.strict_text import require_text_execution, verify_chapter_input


class ExtractionTaskHandler(BaseTaskHandler):
    """提取任务处理器 - 人物/场景/物品提取并写入资产表。"""

    def __init__(
        self,
        *,
        context_loader: ExtractionContextLoader | None = None,
        message_builder: ExtractionMessageBuilder | None = None,
        upsert_service: AssetUpsertService | None = None,
    ) -> None:
        self.context_loader = context_loader or ExtractionContextLoader()
        self.message_builder = message_builder or ExtractionMessageBuilder()
        self.upsert_service = upsert_service or AssetUpsertService()

    async def execute(self, request_params: dict) -> dict:
        execution = require_text_execution(request_params)
        chapter_id = request_params["chapter_id"]
        novel_id = request_params["novel_id"]
        context = await self.context_loader.load(
            novel_id=novel_id,
            chapter_id=chapter_id,
        )
        from services.creation_agent.step_context import step_context
        plan_context = await step_context(request_params)
        from models.chapter import Chapter
        from models.asset import Asset
        from services.creation_agent.memory import creation_memory
        from services.extraction.strict_result import extraction_result
        await verify_chapter_input(request_params)
        facts = self.message_builder.build(context)
        chapter = await Chapter.get(id=chapter_id, novel_id=novel_id)
        assets = await Asset.filter(novel_id=novel_id)
        payload = await execution.generate_strict({
            **facts,
            'constraints': await creation_memory.for_generation(chapter, assets),
            **({'step_context': plan_context.model_dump(mode='json')} if plan_context else {}),
        })
        result = extraction_result(payload, request_params['output_contract']['rendering'])
        from services.creation_agent.operation_receipts import execute_step
        async def persist():
            from services.creation_agent.step_context import step_context, validate_step_inputs
            from services.creation_objects import project_write
            plan_context = await step_context(request_params)
            async with project_write(novel_id):
                await execution.before_request()
                await verify_chapter_input(request_params)
                await validate_step_inputs(request_params)
                from models.asset import Asset
                from models.asset_variant import AssetVariant
                from services.creation_agent.object_state import object_state, object_version, object_label, creation_version
                before = {asset.id: await object_state(asset) for asset in await Asset.filter(novel_id=novel_id)}
                before_variants = {variant.id: await object_state(variant) for variant in
                    await AssetVariant.filter(asset__novel_id=novel_id)}
                options = {'preserve_existing': plan_context.step.mode == 'fill_missing' if plan_context else True, 'include_ids': True}
                summary = await self.upsert_service.save_result(novel_id=novel_id,
                    chapter_number=context.chapter.number, result=result, **options)
                from models.creation_agent import PromptChange
                from services.creation_agent.plan_sources import fingerprint
                identifiers = [item['asset_id'] for group in summary.values() for item in group]
                variant_ids = [item['variant_id'] for group in summary.values() for item in group if 'variant_id' in item]
                summary['asset_ids'] = sorted(set(identifiers))
                summary['variant_ids'] = sorted(set(variant_ids))
                from services.story_memory.context import saved_binding
                provenance = await saved_binding(request_params)
                if provenance:
                    for model, ids in ((Asset, summary['asset_ids']), (AssetVariant, summary['variant_ids'])):
                        for obj in await model.filter(id__in=ids):
                            obj.metadata = {**(obj.metadata or {}), 'story_memory': provenance}
                            await obj.save(update_fields=['metadata'])
                changes = []
                for asset in await Asset.filter(id__in=identifiers):
                    previous, after = before.get(asset.id, {}), await object_state(asset)
                    if previous == after:
                        continue
                    changes.append({'kind': 'asset', 'target_id': asset.id, 'target_label': await object_label(asset),
                        'operation': 'update' if previous else 'create', 'before': previous, 'after': after,
                        'after_version': await object_version(asset), 'constraint_ids': [],
                        'recovery': {} if previous else {'creation_version': await creation_version(asset)}})
                for variant in await AssetVariant.filter(id__in=variant_ids):
                    previous, after = before_variants.get(variant.id, {}), await object_state(variant)
                    if previous == after:
                        continue
                    changes.append({'kind': 'variant', 'target_id': variant.id, 'target_label': await object_label(variant),
                        'operation': 'update' if previous else 'create', 'before': previous, 'after': after,
                        'after_version': await object_version(variant), 'constraint_ids': [],
                        'recovery': {} if previous else {'creation_version': await creation_version(variant)}})
                if changes:
                    await PromptChange.create(novel_id=novel_id, task_id=execution.params['task_id'],
                        tool_call_id='persist:assets', request_hash=fingerprint(result.model_dump()), changes=changes)
                return summary
        summary = await execute_step(execution.params['task_id'], 'persist:assets', persist, atomic=True)
        return {**summary, "token_usage": {}}
