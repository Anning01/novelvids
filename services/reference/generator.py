from services.image_generation import generate_images


def build_sora_compatible_prompt(data: dict, prompt_language: str = "en") -> str:
    """Return the user-editable database prompt without hidden augmentation."""
    del prompt_language  # Kept in the signature for queued-task compatibility.
    value = data.get("base_traits")
    return "" if value is None else str(value).strip()


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
):
    """Execute a reference-image generation task with optional image references."""
    final_prompt = build_sora_compatible_prompt(
        {**data, "aspect_ratio": aspect_ratio},
        prompt_language,
    )

    extra_body = {}

    if reference_images:
        extra_body["image"] = reference_images

    try:
        result = []
        for _ in range(max(1, int(count))):
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
            ))
        return result
    except Exception as error:
        print(f"生成异常: {error}")
        raise
