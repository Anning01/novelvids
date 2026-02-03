"""AI image generation service using Volcengine Ark (Doubao Seedream)."""

import httpx
from loguru import logger

from novelvids.core.config import settings


def build_prompt(asset_type: str, name: str, traits: str, description: str) -> str:
    """
    根据资产类型构建结构化提示词，优化为AI视频生成的最佳参考图。
    生成多角度展示图，白色背景，便于视频模型保持角色/物品一致性。
    """
    # 通用前缀：二次元风格，视频静帧，电影感，高保真
    base_prefix = "二次元风格，视频静帧画面，电影感构图，极高保真度，4K分辨率，"
    
    # 通用后缀：强调无文字、无水印、干净背景
    no_text_suffix = (
        "画面中绝对不要出现任何文字、字母、数字、符号、签名、水印、标志或logo，"
        "保持画面纯净无杂，干净整洁的视觉效果。"
    )

    if asset_type == "person":
        # 角色类：三视图（正面/侧面/背面）+ 白色背景 + 身份锚点
        prompt = (
            f"{base_prefix}角色设定三视图，纯白色无任何图案的背景，"
            f"展示{name}的正面、侧面和背面全身像，"
            f"角色特征：{traits}。{description}。"
            "保持三个角度的服装、发型、体型完全一致，"
            "清晰的轮廓线条，专业的角色设定图风格，"
            f"面部特征精细，五官清晰可辨，便于视频模型追踪识别。{no_text_suffix}"
        )
    elif asset_type == "item":
        # 物品类：多角度产品展示 + 白色背景 + 工作室灯光
        prompt = (
            f"{base_prefix}产品展示图，纯白色无任何图案的背景，"
            f"展示{name}的多角度视图（正面、侧面、45度角），"
            f"物品特征：{traits}。{description}。"
            "专业摄影棚灯光，高光与阴影层次分明，"
            "材质纹理清晰可见，细节丰富，"
            f"产品目录风格，便于视频模型保持物品一致性。{no_text_suffix}"
        )
    elif asset_type == "scene":
        # 场景类：全景展示 + 空间纵深 + 环境氛围
        prompt = (
            f"{base_prefix}场景概念图，电影级宽银幕构图，"
            f"{name}的全景展示，"
            f"场景特征：{traits}。{description}。"
            "广角镜头视角，空间纵深感强烈，"
            "环境光影层次丰富，大气透视效果，"
            f"建立清晰的空间参照系，便于视频模型理解场景布局。{no_text_suffix}"
        )
    else:
        prompt = f"{base_prefix}{name}，{traits}，{description}。{no_text_suffix}"

    return prompt


async def generate_asset_image(
    asset_type: str,
    canonical_name: str,
    base_traits: str,
    description: str | None = None,
    reference_images: list[str] | None = None,
) -> str | None:
    """
    使用 Volcengine Ark API 生成资产图像。

    Args:
        asset_type: 资产类型 (person, scene, item)
        canonical_name: 资产名称
        base_traits: 英文视觉特征
        description: 中文描述
        reference_images: 参考图 URL 列表（用于角色一致性）

    Returns:
        生成的图像 URL，失败返回 None
    """
    if not settings.ark.api_key:
        logger.error("ARK_API_KEY not configured")
        return None

    prompt = build_prompt(
        asset_type=asset_type,
        name=canonical_name,
        traits=base_traits,
        description=description or "",
    )

    logger.info(f"Generating image for {asset_type}: {canonical_name}")
    logger.debug(f"Prompt: {prompt}")

    # 构建请求体
    request_body = {
        "model": settings.ark.model_name,
        "prompt": prompt,
        "size": settings.ark.image_size,
        "response_format": "url",
        "watermark": False,
        # 关键一致性参数：禁用顺序生成以实现多参考图深度融合
        "sequential_image_generation": "disabled",
    }

    # 如果有参考图，添加到请求中
    if reference_images:
        request_body["image"] = reference_images

    try:
        async with httpx.AsyncClient(timeout=settings.ark.timeout) as client:
            response = await client.post(
                f"{settings.ark.base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.ark.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            result = response.json()

            # 提取图像 URL
            if result.get("data") and len(result["data"]) > 0:
                image_url = result["data"][0].get("url")
                logger.info(f"Image generated successfully: {image_url[:100]}...")
                return image_url

            logger.error(f"No image data in response: {result}")
            return None

    except httpx.TimeoutException:
        logger.error(f"Image generation timeout for {canonical_name}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"Image generation HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Image generation failed for {canonical_name}: {e}")
        return None


async def download_and_save_image(
    image_url: str,
    save_path: str,
) -> bool:
    """
    下载图像并保存到本地。

    Args:
        image_url: 图像 URL
        save_path: 本地保存路径

    Returns:
        是否成功
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(image_url)
            response.raise_for_status()

            from pathlib import Path
            path = Path(save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)

            logger.info(f"Image saved to {save_path}")
            return True

    except Exception as e:
        logger.error(f"Failed to download/save image: {e}")
        return False
