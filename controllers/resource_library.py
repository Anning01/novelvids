"""目录规则与资源生命周期编排。"""
from pathlib import Path

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from config import settings
from utils.media_name import video_display_name
from models.scene import Scene
from models.video import Video
from models.resource_library import ResourceFolder, VideoResource
from schemas.resource_library import FolderWrite, ResourceImport
from services.oss import normalize_media_url, resolve_media_url
from services.resource_storage import resource_storage
from services.resource_references import resource_for, reference_dict, validate_resource_model


def resource_dict(resource: VideoResource) -> dict:
    return {
        "id": resource.id, "folder_id": resource.folder_id, "name": video_display_name(resource.name),
        "filename": resource.filename, "url": resolve_media_url(resource.storage_ref),
        "storage_ref": resource.storage_ref, "poster_url": resolve_media_url(resource.poster_ref),
        "state": resource.state, "created_at": resource.created_at,
        **{key: value for key, value in resource.media.items() if not key.startswith("_")},
    }


class ResourceLibraryController:
    async def folder(self, team_id: int, folder_id: int) -> ResourceFolder | None:
        if not folder_id:
            return None
        folder = await ResourceFolder.get_or_none(id=folder_id, team_id=team_id, deleting=False)
        if folder is None:
            raise HTTPException(404, detail="文件夹不存在或正在删除")
        return folder

    async def write_folder(self, team_id: int, user_id: int | None, payload: FolderWrite, folder_id: int | None = None):
        try:
            async with in_transaction():
                folders = await ResourceFolder.filter(team_id=team_id).select_for_update()
                by_id = {item.id: item for item in folders}
                current = by_id.get(folder_id) if folder_id else None
                if folder_id and (current is None or current.deleting):
                    raise HTTPException(404, detail="文件夹不存在或正在删除")
                parent = by_id.get(payload.parent_id) if payload.parent_id else None
                if payload.parent_id and (parent is None or parent.deleting):
                    raise HTTPException(404, detail="目标文件夹不存在")
                if parent and (parent.parent_id or parent.id == folder_id):
                    raise HTTPException(400, detail="文件夹最多两层，不能移入自身或子目录")
                if folder_id and parent and any(item.parent_id == folder_id for item in folders):
                    raise HTTPException(400, detail="包含子文件夹的目录只能放在根目录")
                if current:
                    current.name, current.parent_id = payload.name, payload.parent_id
                    await current.save(update_fields=["name", "parent_id", "updated_at"])
                    return current
                return await ResourceFolder.create(team_id=team_id, created_by=user_id, **payload.model_dump())
        except IntegrityError as exc:
            raise HTTPException(409, detail="同一目录下已有同名文件夹") from exc

    async def reserve(self, team_id: int, user_id: int | None, filename: str, folder_id: int = 0):
        resource_storage.check_filename(filename)
        async with in_transaction():
            if folder_id:
                await ResourceFolder.filter(id=folder_id, team_id=team_id).select_for_update()
            await self.folder(team_id, folder_id)
            return await VideoResource.create(
                team_id=team_id, created_by=user_id, folder_id=folder_id,
                filename=Path(filename).name, name=video_display_name(Path(filename).name),
                storage_ref=resource_storage.new_ref(team_id, filename),
            )

    async def finalize(self, team_id: int, resource_id: int):
        resource = await resource_for(team_id, resource_id, ready=False)
        if resource.state in {"ready", "source"}:
            return resource
        if resource.state != "uploading":
            raise HTTPException(409, detail="上传已结束或正在删除")
        try:
            media, poster = await resource_storage.inspect(resource.storage_ref, resource.filename)
            async with in_transaction():
                if resource.folder_id:
                    await ResourceFolder.filter(id=resource.folder_id, team_id=team_id).select_for_update()
                await self.folder(team_id, resource.folder_id)
                # A concurrent deletion must not resurrect the resource.
                changed = await VideoResource.filter(id=resource.id, state="uploading").update(
                    media=media, poster_ref=poster, state="source" if resource.is_source else "ready",
                )
                if not changed:
                    raise HTTPException(409, detail="上传已被取消")
            await resource.refresh_from_db()
            return resource
        except Exception:
            # Keep failed cleanup retryable through the same deletion lifecycle.
            await VideoResource.filter(id=resource.id, state="uploading").update(
                state="delete_failed", poster_ref=f"{resource.storage_ref}.poster.jpg",
            )
            await self.delete_resources(team_id, [resource.id])
            raise

    async def move(self, team_id: int, ids: list[int], folder_id: int):
        async with in_transaction():
            if folder_id:
                await ResourceFolder.filter(id=folder_id, team_id=team_id).select_for_update()
            await self.folder(team_id, folder_id)
            resources = await VideoResource.filter(id__in=ids, team_id=team_id, state="ready").select_for_update()
            if len(resources) != len(ids):
                raise HTTPException(404, detail="部分资源不存在或无法移动，未移动任何文件")
            await VideoResource.filter(id__in=ids, team_id=team_id).update(folder_id=folder_id)

    async def cancel_upload(self, team_id: int, resource_id: int):
        resource = await resource_for(team_id, resource_id, ready=False)
        if resource.state != "uploading":
            return
        await VideoResource.filter(id=resource_id, team_id=team_id, state="uploading").update(state="delete_failed")
        await self.delete_resources(team_id, [resource_id])

    async def delete_resources(self, team_id: int, ids: list[int]):
        existing = await VideoResource.filter(id__in=ids)
        if any(item.team_id != team_id or item.state == "source" for item in existing):
            raise HTTPException(404, detail="资源不存在")
        if any(item.state == "uploading" for item in existing):
            raise HTTPException(409, detail="视频正在上传或校验，请等待上传完成后再删除")
        # Mark the whole batch before any storage I/O so new references stop immediately.
        await VideoResource.filter(id__in=ids, team_id=team_id).update(state="deleting")
        results = []
        for resource_id in ids:
            resource = await VideoResource.get_or_none(id=resource_id, team_id=team_id)
            if resource is None:
                results.append({"id": resource_id, "deleted": True})
                continue
            try:
                await resource_storage.delete(resource.poster_ref)
                await resource_storage.delete(resource.storage_ref)
                await resource.delete()
                results.append({"id": resource_id, "deleted": True})
            except Exception:
                await VideoResource.filter(id=resource_id).update(state="delete_failed")
                results.append({"id": resource_id, "deleted": False, "error": "存储文件删除失败，请重试"})
        return results

    async def folder_contents(self, team_id: int, folder_id: int):
        folder = await ResourceFolder.get_or_none(id=folder_id, team_id=team_id)
        if folder is None:
            return [], []
        children = await ResourceFolder.filter(team_id=team_id, parent_id=folder_id)
        folder_ids = [folder.id, *[child.id for child in children]]
        resources = await VideoResource.filter(team_id=team_id, folder_id__in=folder_ids).exclude(state="source")
        return folder_ids, [item.id for item in resources]

    async def delete_folder(self, team_id: int, folder_id: int):
        async with in_transaction():
            await ResourceFolder.filter(team_id=team_id).select_for_update()
            folder_ids, resource_ids = await self.folder_contents(team_id, folder_id)
            if await VideoResource.filter(id__in=resource_ids, state="uploading").exists():
                raise HTTPException(409, detail="文件夹内有视频正在上传，请等待上传完成或取消后再删除")
            await ResourceFolder.filter(id__in=folder_ids, team_id=team_id).update(deleting=True)
        results = await self.delete_resources(team_id, resource_ids)
        # Remove children before the parent; preserve any folder containing failed objects.
        for current_id in reversed(folder_ids):
            if not await VideoResource.filter(folder_id=current_id).exists() and not await ResourceFolder.filter(parent_id=current_id).exists():
                await ResourceFolder.filter(id=current_id, team_id=team_id).delete()
        return results

    async def copy_source(self, resource: VideoResource, source_ref: str):
        async with resource_storage.materialize(source_ref) as path:
            if path.stat().st_size > resource_storage.max_bytes:
                raise HTTPException(400, detail="源视频超过资源库大小限制")
            await resource_storage.put(resource.storage_ref, path, "video/mp4")
        return await self.finalize(resource.team_id, resource.id)

    async def import_resource(self, team: int, user_id: int | None, payload: ResourceImport):
        source_ref = None
        filename = "video.mp4"
        if payload.source == "upload":
            source = await VideoResource.get_or_none(id=payload.source_id, team_id=team, state="source")
            if source:
                source_ref, filename = source.storage_ref, source.filename
        elif payload.source == "video":
            video = await Video.get_or_none(id=payload.source_id).select_related("scene__chapter__novel")
            if video and (not settings.AUTH_ENABLED or (video.scene.chapter.novel.team_id or 0) == team) and video.url:
                source_ref = video.url
        else:
            scene = await Scene.get_or_none(id=payload.source_id).select_related("chapter__novel")
            if scene and (not settings.AUTH_ENABLED or (scene.chapter.novel.team_id or 0) == team):
                requested = normalize_media_url(payload.media_url)
                for item in (scene.metadata or {}).get("video_reference_media", []):
                    if item.get("type") == "video" and normalize_media_url(item.get("url")) == requested:
                        source_ref = requested
                        filename = Path(requested).name if requested else filename
                        if not filename.lower().endswith((".mp4", ".mov")):
                            filename = "video.mp4"
                        break
        if not source_ref:
            raise HTTPException(404, detail="未找到当前团队有权访问的源视频")
        resource = await self.reserve(team, user_id, filename, payload.folder_id)
        try:
            resource = await self.copy_source(resource, source_ref)
            resource.name = video_display_name(payload.name.strip() or filename)
            await resource.save(update_fields=["name"])
        except Exception:
            await VideoResource.filter(id=resource.id, state="uploading").update(state="delete_failed")
            await self.delete_resources(team, [resource.id])
            raise
        return resource


resource_library_controller = ResourceLibraryController()
