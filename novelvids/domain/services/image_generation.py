"""AI image generation service using Volcengine Ark (Doubao Seedream)."""

import httpx
from loguru import logger

from novelvids.core.config import settings


def build_prompt(asset_type: str, name: str, traits: str, description: str) -> str:
    """
    根据资产类型构建结构化提示词。
    遵循：主体(Subject) + 行为(Behavior) + 环境(Environment) + 审美(Aesthetics) 逻辑
    """
    # 引导词：加入"视频静帧画面"以适配后续视频生成模型
    base_prefix = "视频静帧画面，"

    if asset_type == "person":
        # 角色类：侧重于面部特征一致性和服装细节
        prompt = (
            f"{base_prefix}主角是{name}，视觉特征为：{traits}。{description}。"
            "二次元风格，电影感布光，中画幅拍摄，皮肤纹理清晰，眼神深邃，高保真渲染。"
        )
    elif asset_type == "item":
        # 物品类：侧重于材质感、光影反射和微距细节
        prompt = (
            f"{base_prefix}{name}的特写，具有{traits}的特征。{description}。"
            "二次元风格，工作室灯光，高保真材质，极细致的纹理，微距镜头。"
        )
    elif asset_type == "scene":
        # 场景类：侧重于空间布局、大气氛围和环境色调
        prompt = (
            f"{base_prefix}{name}的全景，基础架构为：{traits}。{description}。"
            "二次元风格，广角镜头，庄重威严的氛围，丁达尔效应，细腻的光影层次，高分辨率建筑摄影。"
        )
    else:
        prompt = f"{base_prefix}{name}, {traits}, {description}"

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
