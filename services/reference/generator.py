from services.image_generation import generate_images
from prompts.image_references import render_image_reference_mentions


def build_sora_compatible_prompt(data: dict, prompt_language: str = "en") -> str:
    """Return the user-editable database prompt without hidden augmentation."""
    del prompt_language  # Kept in the signature for queued-task compatibility.
    value = data.get("base_traits")
    return "" if value is None else str(value)


async def generate_for_sora_consistency(
    data,
    *,
    base_url,
    api_key,
    api_protocol="openai_compatible",
    reference_images=None,
    model="doubao-seedream-4-5-251128",
    resolution="2K",
    aspect_ratio="16:9",
    count=1,
    output_format="png",
    quality=None,
    prompt_language="en",
    style_prompt="",
    frame_count=9,
    frame_duration_ms=200,
):
    """Execute a reference-image generation task with optional image references."""
    final_prompt = build_sora_compatible_prompt(
        {**data, "aspect_ratio": aspect_ratio},
        prompt_language,
    )
    final_prompt = render_image_reference_mentions(final_prompt, len(reference_images or []), prompt_language)
    if style_prompt:
        final_prompt = f"{final_prompt}\n\n{style_prompt}".strip()
    if output_format == "gif":
        from prompts.image_animation import render_gif_prompt
        final_prompt = render_gif_prompt(final_prompt, frame_count=frame_count, frame_duration_ms=frame_duration_ms, language=prompt_language)

    extra_body = {}
    if output_format == "gif":
        extra_body.update(frame_count=frame_count, frame_duration_ms=frame_duration_ms)

    if reference_images:
        extra_body["image"] = reference_images

    result = []
    for _ in range(max(1, int(count))):
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        if execution:
            await execution.before_request()
        result.extend(await generate_images(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=final_prompt,
            api_protocol=api_protocol,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            count=1,
            output_format=output_format,
            quality=quality,
            extra_body=extra_body,
            **({'timeout': None} if execution else {}),
        ))
    return result
