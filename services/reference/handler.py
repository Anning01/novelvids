
import logging
import os
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from config import settings
from models.asset import Asset
from services.ai_task_executor import BaseTaskHandler
from services.reference.generator import generate_for_sora_consistency
from utils.enums import AssetTypeEnum, ImageSourceEnum

logger = logging.getLogger(__name__)


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

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(remote_url)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)

    media_url = f"/media/assets/{filename}"
    logger.info("Image downloaded: asset_id=%s -> %s", asset_id, media_url)
    return media_url


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

        asset = await Asset.get(id=asset_id)

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

        data = {
            "type": asset_type_name,
            "canonical_name": asset.canonical_name,
            "base_traits": asset.base_traits,
            "description": asset.description,
        }

        # 初始化客户端 (AsyncOpenAI)
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        try:
            image_list = await generate_for_sora_consistency(client, data, model=model)

            result_urls = []
            if image_list:
                # 下载第一张图作为主图
                first_image = image_list[0]
                local_url = await _download_image(first_image.url, asset_id)
                asset.main_image = local_url
                asset.image_source = ImageSourceEnum.ai.value

                await asset.save(update_fields=["main_image", "image_source", "updated_at"])

                result_urls = [local_url]

                # 如果有多张图，下载后续角度图
                for i, img in enumerate(image_list[1:3], start=1):
                    try:
                        angle_url = await _download_image(img.url, asset_id, f"_angle{i}")
                        field_name = f"angle_image_{i}"
                        setattr(asset, field_name, angle_url)
                        await asset.save(update_fields=[field_name, "updated_at"])
                        result_urls.append(angle_url)
                    except Exception:
                        logger.warning("Failed to download angle image %d for asset %s", i, asset_id)

            return {"images": result_urls}

        except Exception as e:
            error_str = str(e)
            if "OutputImageSensitiveContentDetected" in error_str:
                raise Exception("生成图像描述词过于血腥或者暴力，请修改提示词再次尝试") from e
            print(f"Asset reference generation failed for asset {asset_id}")
            raise e
