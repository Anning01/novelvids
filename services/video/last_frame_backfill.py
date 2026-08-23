"""Idempotent compatibility repair for tail frames injected before Prompt binding."""

from __future__ import annotations

from models.scene import Scene
from prompts.video import (
    inject_last_frame_continuity_prompt,
    render_last_frame_continuity_instruction,
)
from services.video.reference_media import reference_mention_syntax


async def backfill_last_frame_continuity() -> dict[str, int]:
    """Bind legacy injected tail frames to their target-scene Prompt on startup."""
    scanned = 0
    updated = 0
    for scene in await Scene.all():
        metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
        raw_media = metadata.get("video_reference_media")
        if not isinstance(raw_media, list):
            continue
        reference = next(
            (
                item
                for item in raw_media
                if isinstance(item, dict)
                and item.get("source") == "previous_scene_last_frame"
                and isinstance(item.get("url"), str)
                and item.get("url")
            ),
            None,
        )
        if reference is None:
            continue

        scanned += 1
        mention_url = str(reference.get("mention_url") or reference["url"])
        mention = reference_mention_syntax("image", mention_url)
        prompt = inject_last_frame_continuity_prompt(scene.prompt or "", mention)
        instruction = render_last_frame_continuity_instruction(mention)
        changed = False
        if reference.get("mention_url") != mention_url:
            reference["mention_url"] = mention_url
            changed = True
        if scene.prompt != prompt:
            scene.prompt = prompt
            changed = True
        if metadata.get("previous_scene_last_frame_prompt_instruction") != instruction:
            metadata["previous_scene_last_frame_prompt_instruction"] = instruction
            changed = True
        if not changed:
            continue
        scene.metadata = metadata
        await scene.save(update_fields=["prompt", "metadata", "updated_at"])
        updated += 1
    return {"scanned": scanned, "updated": updated}
