"""Read portable creative records for one project under its existing project lock."""
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.resource_library import ProjectResource, VideoResource
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterEditDraft, EditorAsset
from services.creation_objects import project_write


# Only creative data crosses installations. Model credentials, identities, leases
# and provider request/response records belong to the originating installation.
FIELDS = {
    Novel: "id name author cover description content total_chapters tags story_outline project_type project_setting episodes_managed audiovisual_guidance shot_duration_max storyboard_enabled storyboard_strategy storyboard_setting style_key workflow_kind aspect_ratio resolution custom_style_prompt video_generation_defaults narrator_audio_reference_id",
    AudioReference: "id nickname gender audio_url avatar_url asset_id source duration is_active",
    VideoResource: "id kind name filename storage_ref poster_ref media is_source state",
    Chapter: "id number name content screenplay status workflow_status",
    Asset: "id asset_type canonical_name aliases description base_traits main_image angle_image_1 angle_image_2 image_source is_global source_chapters last_updated_chapter metadata",
    AssetVariant: "id asset_id name description base_traits chapter_numbers images metadata",
    Scene: "id chapter_id sequence description prompt_params prompt duration status metadata",
    Video: "id scene_id model_type url metadata status",
    EditorAsset: "id kind name media_ref poster_ref sha256 probe size_bytes",
    ChapterEditDraft: "id chapter_id revision document",
    ChapterExport: "id chapter_id source_video_id parent_export_id source_version manifest source_media_ref source_sha256 source_probe recipe media_ref media_sha256 output_probe collection_complete",
    FinishedEpisodePublication: "id chapter_id export_id featured",
    RemakeSource: "id chapter_id episode_number source_kind storage_provider object_key original_filename mime_type size_bytes duration_seconds width height container_format checksum source_video_manifest media_status",
}

PRIVATE_KEYS = frozenset("api_key apikey api_metadata authorization access_token accesstoken refresh_token refreshtoken access_key_id access_key_secret client_secret private_key cookie cookies set-cookie password secret base_url token_usage provider_result request_headers response_headers headers billing_record_id task_id provider_task_id model_config_id video_model_config_id".split())


def creative_value(value):
    if isinstance(value, dict):
        return {k: creative_value(v) for k, v in value.items() if k.lower() not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [creative_value(v) for v in value]
    return value


async def project_snapshot(novel_id: int) -> dict:
    async with project_write(novel_id) as db:
        async def rows(model, **scope):
            data = await model.filter(**scope).using_db(db).order_by("id").values(*FIELDS[model].split())
            return [creative_value(row) for row in data]

        project, = await rows(Novel, id=novel_id)
        chapters = await rows(Chapter, novel_id=novel_id)
        assets = await rows(Asset, novel_id=novel_id)
        variants = await rows(AssetVariant, asset__novel_id=novel_id, asset__deleted_at__isnull=True)
        team = (await Novel.get(id=novel_id).using_db(db)).team_id
        voice_ids = {a["metadata"].get("voice_reference_id") for a in [*assets, *variants] if isinstance(a["metadata"], dict)}
        voice_ids.add(project.get("narrator_audio_reference_id"))
        voices = [int(i) for i in voice_ids if str(i).isdigit()]
        audio = await rows(AudioReference, id__in=voices, team_id__isnull=True)
        if team is not None:
            audio.extend(await rows(AudioReference, id__in=voices, team_id=team))
        library_ids = set(await ProjectResource.filter(novel_id=novel_id).using_db(db).values_list("resource_id", flat=True))
        scenes = await rows(Scene, chapter__novel_id=novel_id)
        links = await Scene.filter(chapter__novel_id=novel_id, assets__novel_id=novel_id,
                                   assets__deleted_at__isnull=True).using_db(db).values_list("id", "assets__id")
        by_scene = {}
        for shot, asset in links:
            by_scene.setdefault(shot, []).append(asset)
        for shot in scenes:
            shot["asset_ids"] = sorted(by_scene.get(shot["id"], []))
            library_ids.update(ref["library_resource_id"] for ref in (shot["metadata"] or {}).get("video_reference_media", [])
                               if isinstance(ref, dict) and isinstance(ref.get("library_resource_id"), int))
        return {
            "novel": project, "chapters": chapters, "assets": assets, "scenes": scenes,
            "variants": variants, "voices": audio,
            "library": await rows(VideoResource, id__in=library_ids, team_id=team or 0),
            "videos": await rows(Video, scene__chapter__novel_id=novel_id, scene__deleted_at__isnull=True),
            "editor_assets": await rows(EditorAsset, novel_id=novel_id),
            "edit_drafts": await rows(ChapterEditDraft, chapter__novel_id=novel_id),
            "exports": await rows(ChapterExport, novel_id=novel_id, chapter_id__in=[c["id"] for c in chapters], collection_complete=True),
            "publications": await rows(FinishedEpisodePublication, chapter__novel_id=novel_id),
            "remake_sources": await rows(RemakeSource, novel_id=novel_id),
        }
