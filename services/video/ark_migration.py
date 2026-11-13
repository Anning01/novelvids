"""Move legacy video channels to Ark while retaining old task query routes."""
from urllib.parse import urlsplit, urlunsplit

from tortoise.transactions import in_transaction

from models.config import AiModelConfig

LEGACY_PROTOCOL = "unified_video"
LEGACY_ROUTE = "legacy_video_query_base"


def ark_base_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    for suffix in ("/v1/videos", "/v1", "/api/v3"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path + "/api/v3", "", ""))


def legacy_query_config(config):
    base_url = (config.processing_options or {}).get(LEGACY_ROUTE)
    if not base_url:
        return None
    return AiModelConfig(id=config.id, base_url=base_url, api_key=config.api_key,
        api_protocol=LEGACY_PROTOCOL, model=config.model, video_model_type=config.video_model_type,
        team_id=config.team_id)


async def migrate_legacy_video_channels() -> None:
    async with in_transaction() as db:
        rows = await AiModelConfig.filter(api_protocol=LEGACY_PROTOCOL).using_db(db).select_for_update()
        for config in rows:
            old_base = config.base_url
            config.processing_options = {**(config.processing_options or {}), LEGACY_ROUTE: old_base}
            config.api_protocol = "volcengine_ark"
            config.base_url = ark_base_url(old_base)
            from models.video import Video
            for video in await Video.filter(external_task_id__not_isnull=True).using_db(db).only("id", "metadata"):
                metadata = video.metadata or {}
                if str(metadata.get("model_config_id")) == str(config.id):
                    await Video.filter(id=video.id).using_db(db).update(metadata={**metadata, "legacy_video_query": True})
            await config.save(using_db=db, update_fields=["processing_options", "api_protocol", "base_url"])
