"""重制拆解结果到通用资产、分镜模型的事务持久化。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from prompts.reference import CHARACTER_TURNAROUND, GROUP_PORTRAIT
from utils.enums import AssetTypeEnum, TaskStatusEnum, WorkflowStatus


class RemakePersistenceError(RuntimeError):
    pass


_ASSET_GROUPS = (
    ("characters", AssetTypeEnum.person),
    ("scenes", AssetTypeEnum.scene),
    ("objects", AssetTypeEnum.item),
)


def named_form(name):
    if "#" in name:
        base, _, form = name.partition("#")
        if base.strip() and form.strip():
            return base.strip(), form.strip()
    match = re.fullmatch(r"(.+?)[（(]([^（）()]+形态)[）)]", name)
    return (match[1].strip(), match[2].strip()) if match else (name, "")


class RemakeResultPersistence:
    async def wait_for_seed(self, seed_task_id, source):
        """Other episodes can cut media now and read the first episode's committed identities before extraction."""
        from models.agent_operation import AgentOperation
        from models.ai_task import AiTask
        if not seed_task_id or not await RemakeSource.filter(novel_id=source.novel_id, analysis_task_id=seed_task_id).exists():
            return
        while await AiTask.filter(id=seed_task_id, status__in=[
            TaskStatusEnum.pending, TaskStatusEnum.queued, TaskStatusEnum.running,
        ]).exists():
            if await AgentOperation.filter(task_id=seed_task_id, key="remake:bindings", state="completed").exists():
                return
            await asyncio.sleep(.5)

    async def project_catalog(self, source):
        from prompts.remake_render import _asset_visual_content
        rows = await Asset.filter(novel_id=source.novel_id).order_by("id").values(
            "id", "canonical_name", "asset_type", "aliases", "description")
        types = {kind.value: group for group, kind in _ASSET_GROUPS}
        variants = {}
        for asset_id, name in await AssetVariant.filter(asset_id__in=[row["id"] for row in rows]).order_by("id").values_list("asset_id", "name"):
            variants.setdefault(asset_id, []).append(name)
        return [{"project_asset_id": row["id"], "forms": variants.get(row["id"], []), "name": row["canonical_name"], "type": types[row["asset_type"]],
                 "aliases": row["aliases"] or [], "visual_identity": _asset_visual_content(row["description"])[:350]}
                for row in rows if row["asset_type"] in types]

    async def bind_assets(self, source, assets, catalog):
        """Resolve episode-local reference IDs before shot generation, in one short project transaction."""
        seen_ids = {item["project_asset_id"] for item in catalog}
        async with in_transaction() as connection:
            await Novel.filter(id=source.novel_id).using_db(connection).select_for_update().get()
            rows = await Asset.filter(novel_id=source.novel_id).using_db(connection).order_by("id")
            by_name = {(row.asset_type, row.canonical_name): row for row in rows}
            aliases = {}
            for row in rows:
                for alias in row.aliases or []:
                    aliases.setdefault((row.asset_type, alias), set()).add(row.canonical_name)
            canonical = {}
            for group, kind in _ASSET_GROUPS:
                canonical[group] = []
                for candidate in assets.get(group, []):
                    name = candidate["name"]
                    names = aliases.get((kind.value, name), set())
                    # An existing fully qualified historical asset remains addressable by its original ID.
                    name, form = (name, "") if (kind.value, name) in by_name else named_form(name)
                    existing = by_name.get((kind.value, name))
                    if existing is None and len(names) == 1:
                        existing = by_name[(kind.value, next(iter(names)))]
                    ambiguous = len(names - {name}) > 0 if existing and existing.canonical_name == name else len(names) > 1
                    if candidate.get("identity_review") and existing:
                        ambiguous = True
                    known_label = existing.metadata.get("remake_label") if existing and isinstance(existing.metadata, dict) else None
                    if kind == AssetTypeEnum.person and known_label and candidate.get("label") and known_label != candidate["label"]:
                        ambiguous = True
                    if existing and existing.id not in seen_ids and (kind == AssetTypeEnum.item or existing.description != candidate["description"]):
                        # Another episode introduced this name after extraction. Name alone is not an identity.
                        ambiguous = True
                    if ambiguous:
                        suffix = f" · EP{source.episode_number}"
                        base = name
                        ordinal = 1
                        while (kind.value, base[:100 - len(suffix)] + suffix) in by_name:
                            ordinal += 1
                            suffix = f" · EP{source.episode_number}-{ordinal}"
                        name = base[:100 - len(suffix)] + suffix
                        existing = None
                    item = {**candidate, "name": existing.canonical_name if existing else name}
                    if form:
                        item["form_name"] = form
                    if ambiguous:
                        item["identity_review"] = True
                    if existing:
                        item["project_asset_id"] = existing.id
                    canonical[group].append(item)
            bound = await self._persist_assets(connection, source=source, assets=canonical, preserve_existing=True)
            for items in canonical.values():
                for item in items:
                    asset = bound[item["id"]]
                    item["project_asset_id"] = asset.id
                    if form := item.get("form_name"):
                        variant, _ = await AssetVariant.get_or_create(asset=asset, name=form, using_db=connection,
                            defaults={"description": item["description"], "base_traits": item["description"]})
                        chapters = sorted(set(variant.chapter_numbers or []) | {source.episode_number})
                        if variant.chapter_numbers != chapters:
                            variant.chapter_numbers = chapters
                            await variant.save(using_db=connection, update_fields=["chapter_numbers", "updated_at"])
                        item["project_variant_id"] = variant.id
                        item["name"] = f"{asset.canonical_name}#{form}"
            return canonical

    async def persist(
        self,
        *,
        source: RemakeSource,
        assets: dict[str, list[dict[str, Any]]],
        prompt_document: dict[str, Any],
        pipeline_metadata: dict[str, Any],
    ) -> dict[str, int]:
        from prompts.skill_pack import SkillSnapshot, snapshot_skills
        from services.creation_agent.skill_execution import current_execution
        from services.language import task_language
        from services.remake.prompt_render import compact_catalog
        from services.remake.storyboards import prepare_remake_prompt

        execution = current_execution.get()
        snapshot = execution.snapshot if execution else SkillSnapshot.model_validate(snapshot_skills())
        project = await Novel.get(id=source.novel_id)
        language = execution.language if execution else task_language.get() or 'zh'
        catalog = compact_catalog(assets, snapshot=snapshot, language=language)
        prompts = [
            prepare_remake_prompt(item, catalog, snapshot, language, strategy_key=project.storyboard_strategy,
                                 duration_seconds=item.get('duration_seconds'))
            for item in prompt_document.get("prompts", [])
            if isinstance(item, dict)
        ]
        async with in_transaction() as connection:
            await Novel.filter(id=source.novel_id).using_db(connection).select_for_update().get()
            asset_index = await self._persist_assets(
                connection,
                source=source,
                assets=assets,
            )
            forms = {item["id"]: item.get("project_variant_id") for items in assets.values() for item in items
                     if item.get("project_asset_id")}
            variant_ids = {variant for variant in forms.values() if variant is not None}
            if variant_ids:
                owners = dict(await AssetVariant.filter(id__in=list(variant_ids)).using_db(connection)
                              .select_for_update().values_list("id", "asset_id"))
                if any(owners.get(variant) != asset_index[key].id for key, variant in forms.items() if variant is not None):
                    raise RemakePersistenceError("重制引用的资产形态已变化，请核对后再保存")
            scene_count = await self._persist_scenes(
                connection,
                source=source,
                prompts=prompts,
                asset_index=asset_index,
                forms=forms,
                pipeline_metadata=pipeline_metadata,
            )
            await Chapter.filter(id=source.chapter_id).using_db(connection).update(
                status=TaskStatusEnum.completed.value,
                workflow_status=WorkflowStatus.storyboard_ready.value,
            )
            await RemakeSource.filter(id=source.id).using_db(connection).update(
                media_status="completed"
            )
        source.media_status = "completed"
        return {"asset_count": len(asset_index), "scene_count": scene_count}

    async def _persist_assets(
        self,
        connection: BaseDBAsyncClient,
        *,
        source: RemakeSource,
        assets: dict[str, list[dict[str, Any]]],
        preserve_existing: bool = False,
    ) -> dict[str, Asset]:
        from services.extraction.extractor import validate_asset_design

        result: dict[str, Asset] = {}
        chapter = await Chapter.get(id=source.chapter_id).using_db(connection)
        for group, asset_type in _ASSET_GROUPS:
            for item in assets.get(group, []):
                if not isinstance(item, dict):
                    continue
                reference_id = str(item.get("id", "")).strip()
                name = str(item.get("name", "")).strip()
                if not reference_id or not name:
                    continue
                description = str(item.get("description", "")).strip()
                validate_asset_design(description)
                layout = ({'reference_layout':GROUP_PORTRAIT if item.get('label') == '群像' else CHARACTER_TURNAROUND}
                          if asset_type == AssetTypeEnum.person else {})
                identity = item.get("project_asset_id")
                if identity is not None:
                    existing = await Asset.get_or_none(id=identity, novel_id=source.novel_id,
                                                       asset_type=asset_type.value).using_db(connection)
                    if existing is None:
                        raise RemakePersistenceError(f"重制资产已移除：{name}")
                else:
                    existing = await Asset.get_or_none(novel_id=source.novel_id, asset_type=asset_type.value,
                                                       canonical_name=name).using_db(connection)
                if existing is None:
                    existing = await Asset.create(
                        using_db=connection,
                        novel_id=source.novel_id,
                        asset_type=asset_type.value,
                        canonical_name=name,
                        aliases=[],
                        description=description,
                        base_traits=description,
                        is_global=True,
                        source_chapters=[chapter.number],
                        last_updated_chapter=chapter.number,
                        metadata={
                            **layout,
                            "analysis_source": "remake_decomposition",
                            "remake_source_id": source.id,
                            "remake_source_ids": [source.id],
                            "remake_reference_id": reference_id,
                            "remake_label": str(item.get("label", "")),
                            **({"identity_review": True} if item.get("identity_review") else {}),
                        },
                    )
                else:
                    metadata = existing.metadata if isinstance(existing.metadata, dict) else {}
                    raw_source_ids = metadata.get("remake_source_ids")
                    source_ids = [
                        int(value)
                        for value in (raw_source_ids if isinstance(raw_source_ids, list) else [])
                        if isinstance(value, int)
                    ]
                    legacy_source_id = metadata.get("remake_source_id")
                    if isinstance(legacy_source_id, int) and legacy_source_id not in source_ids:
                        source_ids.append(legacy_source_id)
                    if source.id not in source_ids:
                        source_ids.append(source.id)
                        source_ids.sort()
                    owned = (
                        metadata.get("analysis_source") == "remake_decomposition"
                        and not preserve_existing and identity is None and legacy_source_id == source.id
                    )
                    chapters = list(existing.source_chapters or [])
                    if chapter.number not in chapters:
                        chapters.append(chapter.number)
                        chapters.sort()
                    existing.source_chapters = chapters
                    if owned:
                        existing.description = description
                        existing.base_traits = description
                        existing.last_updated_chapter = chapter.number
                        existing.metadata = {
                            **metadata,
                            **layout,
                            "remake_source_ids": source_ids,
                            "remake_reference_id": reference_id,
                            "remake_label": str(item.get("label", "")),
                        }
                        update_fields = [
                            "description",
                            "base_traits",
                            "source_chapters",
                            "last_updated_chapter",
                            "metadata",
                            "updated_at",
                        ]
                    else:
                        existing.metadata = {
                            **metadata,
                            "remake_source_ids": source_ids,
                        }
                        update_fields = ["source_chapters", "metadata", "updated_at"]
                    await existing.save(using_db=connection, update_fields=update_fields)
                result[reference_id] = existing
        return result

    async def _persist_scenes(
        self,
        connection: BaseDBAsyncClient,
        *,
        source: RemakeSource,
        prompts: list[dict[str, Any]],
        asset_index: dict[str, Asset],
        forms: dict,
        pipeline_metadata: dict[str, Any],
    ) -> int:
        sequences: set[int] = set()
        for position, item in enumerate(prompts, start=1):
            sequence = _positive_int(item.get("shot_index"), position)
            sequences.add(sequence)
            scene = await Scene.get_or_none(
                chapter_id=source.chapter_id,
                sequence=sequence,
            ).using_db(connection)
            metadata = scene.metadata if scene and isinstance(scene.metadata, dict) else {}
            if scene is not None and metadata.get("remake_source_id") != source.id:
                raise RemakePersistenceError(
                    f"第 {sequence} 个分镜已存在，无法覆盖非重制生成内容"
                )
            scene_metadata = {
                **metadata,
                "analysis_source": "remake_decomposition",
                "remake_source_id": source.id,
                "source_file": str(item.get("file", "")),
                "confidence": item.get("confidence"),
                "pipeline": dict(pipeline_metadata),
            }
            if forms:
                bindings = {}
                for ref in item.get("asset_refs", []):
                    key = ref["asset_id"]
                    if key in forms:
                        choices = bindings.setdefault(str(asset_index[key].id), [])
                        if forms[key] not in choices:
                            choices.append(forms[key])
                scene_metadata["asset_variant_ids"] = bindings
            if scene is None:
                scene = await Scene.create(
                    using_db=connection,
                    chapter_id=source.chapter_id,
                    sequence=sequence,
                    description=f"重制镜头 {sequence}",
                    prompt_params=item,
                    prompt=str(item.get("prompt", "")),
                    duration=float(item.get("duration_seconds", 0) or 0),
                    status=TaskStatusEnum.pending.value,
                    metadata=scene_metadata,
                )
            else:
                scene.description = f"重制镜头 {sequence}"
                scene.prompt_params = item
                scene.prompt = str(item.get("prompt", ""))
                scene.duration = float(item.get("duration_seconds", 0) or 0)
                scene.metadata = scene_metadata
                await scene.save(
                    using_db=connection,
                    update_fields=[
                        "description",
                        "prompt_params",
                        "prompt",
                        "duration",
                        "metadata",
                        "updated_at",
                    ],
                )
            await scene.assets.clear(using_db=connection)
            referenced = []
            for reference in item.get("asset_refs", []):
                if not isinstance(reference, dict):
                    continue
                asset = asset_index.get(str(reference.get("asset_id", "")))
                if asset is not None and asset not in referenced:
                    referenced.append(asset)
            if referenced:
                await scene.assets.add(*referenced, using_db=connection)

        owned_scenes = await Scene.filter(chapter_id=source.chapter_id).using_db(connection)
        for scene in owned_scenes:
            metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
            if (
                metadata.get("remake_source_id") == source.id
                and scene.sequence not in sequences
            ):
                await scene.delete(using_db=connection)
        return len(sequences)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return fallback
    return result if result > 0 else fallback


remake_result_persistence = RemakeResultPersistence()
