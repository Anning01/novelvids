"""共享视频引用的团队、生命周期和模型能力校验。"""
from fastapi import HTTPException
from utils.media_name import video_display_name

from models.resource_library import VideoResource
from services.oss import resolve_media_url
from services.video.reference_media import _validate_probe, media_kind_for_extension


async def resource_for(team_id: int, resource_id: int, *, ready: bool = True) -> VideoResource:
    resource = await VideoResource.get_or_none(id=resource_id, team_id=team_id)
    if resource is None or (ready and resource.state != "ready"):
        raise HTTPException(404, detail="资源视频不存在、正在删除或已删除，请重新选择")
    return resource


def reference_dict(resource: VideoResource) -> dict:
    return {
        "type": "video", "url": resolve_media_url(resource.storage_ref) or resource.storage_ref,
        "mention_url": resource.storage_ref, "name": video_display_name(resource.name),
        "library_resource_id": resource.id,
        **{key: value for key, value in resource.media.items() if not key.startswith("_")},
    }


def validate_resource_model(resource: VideoResource, capabilities) -> None:
    if not capabilities.max_reference_videos:
        raise HTTPException(400, detail="当前模型不支持参考视频")
    media_kind_for_extension(resource.filename, capabilities)
    _validate_probe("video", resource.media.get("_probe", {}), resource.media.get("size_bytes", 0), capabilities)
