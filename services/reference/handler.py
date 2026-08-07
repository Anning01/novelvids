
import base64
import binascii
import logging
import os
from urllib.parse import urlparse

import httpx

from config import settings
from models.asset import Asset
from models.asset_variant import AssetVariant
from services.ai_task_executor import BaseTaskHandler
from services.reference.generator import generate_for_sora_consistency
from utils.enums import AssetTypeEnum, ImageSourceEnum

logger = logging.getLogger(__name__)


def _image_extension(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    raise RuntimeError("生图供应商返回了不支持的图片格式")


def _save_base64_image(encoded: str, asset_id: int, suffix: str = "") -> str:
    payload = (
        encoded.split(",", 1)[1]
        if encoded.startswith("data:") and "," in encoded
        else encoded
    )
    try:
        content = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise RuntimeError("生图供应商返回了无效的 base64 图片") from error
    extension = _image_extension(content)
    asset_dir = os.path.join(settings.MEDIA_PATH, "assets")
    os.makedirs(asset_dir, exist_ok=True)
    filename = f"{asset_id}{suffix}{extension}"
    with open(os.path.join(asset_dir, filename), "wb") as file:
        file.write(content)
    return f"/media/assets/{filename}"


async def _download_image(remote_url: str, asset_id: int, suffix: str = "") -> str:
    """下载远程图片到本地 MEDIA_PATH/assets/ 目录，返回可访问的相对路径。

    Args:
        remote_url: 远程图片 URL
        asset_id: 资产 ID（用于文件名）
        suffix: 文件名后缀，如 "_angle1"

    Returns:
        可通过 /media/ 前缀访问的路径，如 /media/assets/42.png
    """
    asset_dir = os.path.join(settings.MEDIA_PATH, "assets")
    os.makedirs(asset_dir, exist_ok=True)

    # 从 URL 推断扩展名，默认 .png
    parsed = urlparse(remote_url)
    ext = os.path.splitext(parsed.path)[1] or ".png"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".png"

    filename = f"{asset_id}{suffix}{ext}"
    local_path = os.path.join(asset_dir, filename)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(remote_url)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)

    media_url = f"/media/assets/{filename}"
    logger.info("Image downloaded: asset_id=%s -> %s", asset_id, media_url)
    return media_url


async def _persist_generated_image(image, asset_id: int, suffix: str) -> str:
    remote_url = getattr(image, "url", None)
    if isinstance(remote_url, str) and remote_url:
        return await _download_image(remote_url, asset_id, suffix)
    encoded = getattr(image, "b64_json", None)
    if isinstance(encoded, str) and encoded:
        return _save_base64_image(encoded, asset_id, suffix)
    raise RuntimeError("生图供应商返回的图片缺少 URL 和 base64 内容")


class AssetReferenceHandler(BaseTaskHandler):
    """资产参考图生成任务处理器。"""

    async def execute(self, request_params: dict) -> dict:
        """
        request_params:
            asset_id: int
            base_url: str
            api_key: str
            model: str
        """
        asset_id = request_params["asset_id"]
        base_url = request_params["base_url"]
        api_key = request_params["api_key"]
        model = request_params["model"]
        api_protocol = request_params.get("api_protocol", "openai_compatible")
        variant_id = request_params.get("variant_id")
        prompt_language = request_params.get("prompt_language", "en")

        asset = await Asset.get(id=asset_id)
        variant = None
        if variant_id is not None:
            variant = await AssetVariant.get(id=variant_id, asset_id=asset_id)

        # 构造生成所需的数据
        try:
            asset_type_enum = AssetTypeEnum(asset.asset_type)
            asset_type_name = asset_type_enum.name
        except ValueError:
            if asset.asset_type == 1:
                asset_type_name = "person"
            elif asset.asset_type == 2:
                asset_type_name = "scene"
            elif asset.asset_type == 3:
                asset_type_name = "item"
            else:
                asset_type_name = "unknown"

        metadata = {
            **(asset.metadata or {}),
            **((variant.metadata or {}) if variant else {}),
        }
        workbench = (
            metadata.get("workbench")
            if isinstance(metadata.get("workbench"), dict)
            else {}
        )
        resolution = metadata.get("resolution") or workbench.get("resolution") or "2K"
        aspect_ratio = (
            metadata.get("aspect_ratio")
            or workbench.get("aspectRatio")
            or "16:9"
        )
        generation_count = (
            metadata.get("generation_count")
            or workbench.get("generationCount")
            or 1
        )
        data = {
            "type": asset_type_name,
            "canonical_name": asset.canonical_name,
            "base_traits": (
                variant.base_traits
                if variant and variant.base_traits
                else asset.base_traits
            ),
            "description": (
                variant.description
                if variant and variant.description
                else asset.description
            ),
            "metadata": metadata,
        }

        try:
            image_list = await generate_for_sora_consistency(
                data,
                base_url=base_url,
                api_key=api_key,
                api_protocol=api_protocol,
                model=model,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                count=generation_count,
                prompt_language=prompt_language,
            )

            result_urls = []
            if image_list:
                for index, image in enumerate(image_list):
                    try:
                        suffix = (
                            f"_variant{variant.id}_{index + 1}"
                            if variant
                            else "" if index == 0 else f"_candidate{index + 1}"
                        )
                        result_urls.append(
                            await _persist_generated_image(image, asset_id, suffix)
                        )
                    except Exception as error:
                        remote_url = getattr(image, "url", None)
                        logger.warning(
                            "Reference image download failed: asset_id=%s "
                            "image=%d host=%s error=%s",
                            asset_id,
                            index + 1,
                            urlparse(remote_url).netloc if remote_url else "base64",
                            type(error).__name__,
                        )

                if variant:
                    variant.images = result_urls
                    await variant.save(update_fields=["images", "updated_at"])
                elif result_urls:
                    asset.main_image = result_urls[0]
                    asset.angle_image_1 = result_urls[1] if len(result_urls) > 1 else None
                    asset.angle_image_2 = result_urls[2] if len(result_urls) > 2 else None
                    asset.image_source = ImageSourceEnum.ai.value
                    asset.metadata = {
                        **(asset.metadata or {}),
                        "image_gallery": result_urls,
                    }
                    await asset.save(
                        update_fields=[
                            "main_image",
                            "angle_image_1",
                            "angle_image_2",
                            "image_source",
                            "metadata",
                            "updated_at",
                        ]
                    )

            if not result_urls:
                raise RuntimeError("参考图生成完成，但没有可持久化的图片")

            return {"images": result_urls, "variant_id": variant.id if variant else None}

        except Exception as error:
            error_str = str(error)
            if "OutputImageSensitiveContentDetected" in error_str:
                raise RuntimeError(
                    "生成图像描述词过于血腥或者暴力，请修改提示词再次尝试"
                ) from error
            raise
