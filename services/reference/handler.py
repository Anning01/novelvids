
from openai import AsyncOpenAI

from models.asset import Asset
from services.ai_task_executor import BaseTaskHandler
from services.reference.generator import generate_for_sora_consistency
from utils.enums import AssetTypeEnum, ImageSourceEnum



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
            # Fallback specifically for safety
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
            # 直接异步调用
            image_list = await generate_for_sora_consistency(client, data, model=model)

            result_urls = []
            if image_list:
                # 更新 Asset
                # 取第一张图作为主图
                first_image = image_list[0]
                asset.main_image = first_image.url
                # 标记图片来源为 AI
                asset.image_source = ImageSourceEnum.ai.value

                await asset.save(update_fields=["main_image", "image_source", "updated_at"])

                result_urls = [img.url for img in image_list]

            return {"images": result_urls}

        except Exception as e:
            print(f"Asset reference generation failed for asset {asset_id}")
            raise e
