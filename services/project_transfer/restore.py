"""Restore a verified creative graph under fresh local identities in one transaction."""
from datetime import datetime, timezone
from uuid import uuid4

from tortoise.transactions import in_transaction

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.novel import Novel
from models.portfolio import PortfolioWork, PortfolioEpisode
from services.project_transfer.sync_identity import restore_mappings
from models.remake_source import RemakeSource
from models.resource_library import ProjectResource, VideoResource
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterCanvasSnapshot, ChapterEditDraft, EditorAsset
from services.project_transfer.canvas import rebind_layout
from services.project_transfer.archive import ArchiveError
from services.project_transfer.snapshot import FIELDS, creative_value
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class LocalIds:
    def __init__(self):
        self.tables = {}

    def add(self, model, old, new):
        table = self.tables.setdefault(model, {})
        if type(old) is not int or old < 1 or old in table:
            raise ArchiveError("作品包存在无效或重复的记录编号")
        table[old] = new

    def get(self, model, old):
        if old is None:
            return None
        try:
            return self.tables[model][int(old)]
        except (KeyError, TypeError, ValueError):
            raise ArchiveError("作品引用的记录未包含在迁移包内") from None

    def references(self, value):
        if isinstance(value, list):
            return [self.references(v) for v in value]
        if not isinstance(value, dict):
            return value
        output = {}
        scalar = {"scene_id": Scene, "chapter_id": Chapter, "variant_id": AssetVariant, "current_video_id": Video,
                  "source_video_id": Video, "video_id": Video, "voice_reference_id": AudioReference,
                  "narrator_audio_reference_id": AudioReference, "library_resource_id": VideoResource}
        for key, item in value.items():
            if key == "asset_variant_ids" and isinstance(item, dict):
                output[key] = {str(self.get(Asset, k)): [self.get(AssetVariant, identifier) for identifier in v] if isinstance(v, list) else self.get(AssetVariant, v) for k, v in item.items()}
            elif key in {"asset_ids", "voice_asset_ids"} and isinstance(item, list) and all(type(v) is int for v in item):
                output[key] = [self.get(Asset, v) for v in item]
            elif key == "asset_id" and type(item) is int:
                output[key] = self.get(Asset, item)
            elif key in scalar and type(item) is int:
                output[key] = self.get(scalar[key], item)
            elif key in {"video_prompt_tasks", "auto_enhancement", "modelType", "activeVideoId", "restored_generation_task_id"}:
                if key == "activeVideoId" and item is not None:
                    output[key] = self.get(Video, item)
            elif key == "source" and isinstance(item, dict) and "id" in item and item.get("kind") in {"asset","video","library","missing"}:
                kind = {"asset": EditorAsset, "video": Video, "library": VideoResource, "missing": Scene}[item["kind"]]
                output[key] = {**item, "id": self.get(kind, item["id"])}
            else:
                output[key] = self.references(item)
        return output


async def restore_graph(project, *, team_id, user_id):
    ids = LocalIds()
    scope = {"team_id": team_id, "created_by": user_id}
    async with in_transaction() as db:
        async def create(model, row, *, omit=(), **overrides):
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                raise ArchiveError("作品记录无效")
            values = {k: creative_value(row[k]) for k in FIELDS[model].split()
                      if k != "id" and k not in omit and k in row}
            saved = await model.create(using_db=db, **{**values, **overrides})
            ids.add(model, row["id"], saved.id)
            return saved

        for voice in project["voices"]:
            # A system voice already installed locally has a stable source identity.
            existing = await AudioReference.get_or_none(asset_id=voice["asset_id"], source="system", team_id=None).using_db(db)
            if voice.get("source") == "system" and existing:
                ids.add(AudioReference, voice["id"], existing.id)
            else:
                await create(AudioReference, voice, source="upload", asset_id=uuid4().hex, **scope)
        row = project["novel"]
        base = str(row.get("name") or "").strip()
        if not base:
            raise ArchiveError("作品缺少名称")
        name, suffix = base, 1
        while await Novel.filter(team_id=team_id, name=name).using_db(db).exists():
            suffix += 1
            name = f"{base[:240]} ({suffix})"
        novel = await create(Novel, row, name=name, narrator_audio_reference_id=ids.get(AudioReference, row.get("narrator_audio_reference_id")),
                             video_generation_defaults=ids.references(row.get("video_generation_defaults")), **scope)
        for source in project["library"]:
            resource = await create(VideoResource, source, **{**scope,"team_id":team_id or 0})
            await ProjectResource.create(novel_id=novel.id, resource_id=resource.id, using_db=db)
        for row in project["chapters"]:
            await create(Chapter, row, novel_id=novel.id)
        for row in project["editor_assets"]:
            await create(EditorAsset, row, novel_id=novel.id, **scope)
        for row in project["assets"]:
            await create(Asset, row, novel_id=novel.id, metadata={})
        for row in project["variants"]:
            await create(AssetVariant, row, asset_id=ids.get(Asset,row["asset_id"]), metadata={})
        for row in project["scenes"]:
            scene = await create(Scene, row, chapter_id=ids.get(Chapter,row["chapter_id"]), metadata={}, prompt_params={})
            for old in row.get("asset_ids", []):
                await scene.assets.add(await Asset.get(id=ids.get(Asset,old)).using_db(db), using_db=db)
        for row in project["videos"]:
            status = row["status"]
            if status in (TaskStatusEnum.pending, TaskStatusEnum.running, TaskStatusEnum.queued):
                status = TaskStatusEnum.cancelled.value
            await create(Video, row, scene_id=ids.get(Scene,row["scene_id"]), metadata={}, status=status)
        for model, group in [(Asset,"assets"), (AssetVariant,"variants"), (Scene,"scenes"), (Video,"videos")]:
            for row in project[group]:
                changes = {"metadata": ids.references(row.get("metadata") or {})}
                if model is Scene:
                    changes["prompt_params"] = ids.references(row.get("prompt_params"))
                await model.filter(id=ids.get(model,row["id"])).using_db(db).update(**changes)
        for row in project["remake_sources"]:
            await create(RemakeSource, row, chapter_id=ids.get(Chapter,row["chapter_id"]), novel_id=novel.id,
                         storage_provider="local", source_video_manifest=ids.references(row.get("source_video_manifest")), **scope)
        for row in project["edit_drafts"]:
            await create(ChapterEditDraft, row, chapter_id=ids.get(Chapter,row["chapter_id"]),
                         document=ids.references(row["document"]), updated_by=user_id)
        for row in sorted(project["exports"], key=lambda r:r["id"]):
            # The finished-episode library uses a completed task to identify playable versions.
            # This is an import receipt only; it is never scheduled or charged.
            receipt = await AiTask.create(using_db=db, task_type=AiTaskTypeEnum.video, status=TaskStatusEnum.completed,
                stage="project_import", finished_at=datetime.now(timezone.utc),
                request_params={"operation":"project_import", "novel_id":novel.id, "team_id":team_id, "user_id":user_id})
            await create(ChapterExport, row, novel_id=novel.id, chapter_id=ids.get(Chapter,row["chapter_id"]),
                source_video_id=ids.get(Video,row.get("source_video_id")),
                parent_export_id=ids.get(ChapterExport,row.get("parent_export_id")), identity_key=uuid4().hex, task_id=receipt.id,
                manifest=ids.references(row["manifest"]), recipe=ids.references(row["recipe"]), **scope)
        for row in project["publications"]:
            await create(FinishedEpisodePublication, row, chapter_id=ids.get(Chapter,row["chapter_id"]),
                         export_id=ids.get(ChapterExport,row.get("export_id")))
        for row in project.get("portfolio",[]):
            await create(PortfolioWork,row,novel_id=novel.id,cover_chapter_id=ids.get(Chapter,row.get("cover_chapter_id")),
                         status="private",featured=False)
        for row in project.get("portfolio_episodes",[]):
            await create(PortfolioEpisode,row,work_id=ids.get(PortfolioWork,row["work_id"]),chapter_id=ids.get(Chapter,row["chapter_id"]),
                         export_id=ids.get(ChapterExport,row["export_id"]))
        await restore_mappings(project.get("sync_works",[]),ids,novel.id,team_id,db)
        for chapter_id,layout in project.get("canvases",{}).items():
            await ChapterCanvasSnapshot.create(using_db=db,chapter_id=ids.get(Chapter,chapter_id),layout=rebind_layout(layout,ids))
        return novel
