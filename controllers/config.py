from fastapi import HTTPException

from models.config import AiModelConfig, GeneralConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate, GeneralConfigUpdate
from services.image_generation.capabilities import (
    capabilities_for as image_capabilities_for,
    validate_protocol as validate_image_protocol,
)
from services.video.capabilities import (
    capabilities_for as video_capabilities_for,
    validate_protocol as validate_video_protocol,
)
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, ImageModelTypeEnum, VideoGenerationModelTypeEnum


def _validate_text_pricing(pricing: dict) -> None:
    if pricing.get("type") != "text":
        raise HTTPException(status_code=400, detail="文本模型的费用配置 type 必须为 text")
    for key in ("input_price_per_1m", "output_price_per_1m"):
        value = pricing.get(key)
        if value is None or not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"文本费用缺少合法的 {key}")


def _validate_image_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "image":
        raise HTTPException(status_code=400, detail="生图模型的费用配置 type 必须为 image")
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail="生图费用需要 prices 档位对象")
    allowed = set(image_capabilities_for(model_type).clarities)
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=f"生图费用包含不支持的清晰度档位：{tier}")
        if not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"清晰度档位 {tier} 的费用必须为非负数字")


def _validate_video_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "video":
        raise HTTPException(status_code=400, detail="视频模型的费用配置 type 必须为 video")
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail="视频费用需要 prices 档位对象")
    allowed = set(video_capabilities_for(model_type).resolutions)
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=f"视频费用包含不支持的分辨率档位：{tier}")
        if not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"分辨率档位 {tier} 的费用必须为非负数字")


class AiModelConfigController(CRUDBase[AiModelConfig, AiModelConfigCreate, AiModelConfigUpdate]):
    def __init__(self):
        super().__init__(model=AiModelConfig)

    @staticmethod
    def _capabilities(config: AiModelConfig) -> set[int]:
        return {int(value) for value in (config.task_types or [config.task_type])}

    @staticmethod
    def _normalize_payload(obj_in) -> dict:
        data = obj_in.model_dump(exclude_unset=True, exclude={"id"})
        if "task_types" in data:
            values = list(dict.fromkeys(int(value) for value in (data["task_types"] or [])))
            if not values:
                values = [int(data.get("task_type"))]
            data["task_types"] = values
            data["task_type"] = values[0]
        elif "task_type" in data:
            data["task_types"] = [int(data["task_type"])]
        return data

    @staticmethod
    def _validate_image_payload(data: dict, instance: AiModelConfig | None = None) -> None:
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        if AiTaskTypeEnum.reference_image.value not in (task_types or []):
            return
        model_type = data.get("image_model_type")
        if model_type is None and instance is not None:
            model_type = instance.image_model_type
        protocol = data.get("api_protocol")
        if protocol is None and instance is not None:
            protocol = instance.api_protocol
        image_capabilities_for(model_type)
        validate_image_protocol(model_type, str(protocol))

    @staticmethod
    def _validate_video_payload(data: dict, instance: AiModelConfig | None = None) -> None:
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        if AiTaskTypeEnum.video.value not in (task_types or []):
            return
        model_type = data.get("video_model_type")
        if model_type is None and instance is not None:
            model_type = instance.video_model_type
        protocol = data.get("api_protocol")
        if protocol is None and instance is not None:
            protocol = instance.api_protocol
        video_capabilities_for(model_type)
        validate_video_protocol(model_type, str(protocol))

    @staticmethod
    def _validate_pricing(data: dict, instance: AiModelConfig | None = None) -> None:
        pricing = data.get("pricing")
        if pricing is None:
            return
        if not isinstance(pricing, dict):
            raise HTTPException(status_code=400, detail="费用配置必须是对象")
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        task_types = [int(value) for value in (task_types or [])]
        if AiTaskTypeEnum.reference_image.value in task_types:
            model_type = data.get("image_model_type") or (
                instance.image_model_type if instance else None
            )
            _validate_image_pricing(pricing, model_type)
            return
        if AiTaskTypeEnum.video.value in task_types:
            model_type = data.get("video_model_type") or (
                instance.video_model_type if instance else None
            )
            _validate_video_pricing(pricing, model_type)
            return
        _validate_text_pricing(pricing)

    @classmethod
    def _validate_generation_payload(cls, data: dict, instance: AiModelConfig | None = None) -> None:
        cls._validate_image_payload(data, instance)
        cls._validate_video_payload(data, instance)
        cls._validate_pricing(data, instance)

    @staticmethod
    async def _enforce_single_active_image_type(instance: AiModelConfig) -> None:
        if not instance.is_active or not instance.image_model_type:
            return
        if AiTaskTypeEnum.reference_image.value not in AiModelConfigController._capabilities(instance):
            return
        await AiModelConfig.filter(
            is_active=True,
            image_model_type=instance.image_model_type,
        ).exclude(id=instance.id).update(is_active=False)

    @staticmethod
    async def _enforce_single_active_video_type(instance: AiModelConfig) -> None:
        if not instance.is_active or not instance.video_model_type:
            return
        if AiTaskTypeEnum.video.value not in AiModelConfigController._capabilities(instance):
            return
        await AiModelConfig.filter(
            is_active=True,
            video_model_type=instance.video_model_type,
        ).exclude(id=instance.id).update(is_active=False)

    @classmethod
    async def _enforce_single_active_generation_type(cls, instance: AiModelConfig) -> None:
        await cls._enforce_single_active_image_type(instance)
        await cls._enforce_single_active_video_type(instance)

    async def create(self, obj_in: AiModelConfigCreate, **kwargs) -> AiModelConfig:
        data = self._normalize_payload(obj_in)
        self._validate_generation_payload(data)
        instance = await super().create(data, **kwargs)
        await self._enforce_single_active_generation_type(instance)
        return instance

    async def update(self, config_id: int, obj_in: AiModelConfigUpdate) -> AiModelConfig:
        instance = await self.get(config_id)
        data = self._normalize_payload(obj_in)
        self._validate_generation_payload(data, instance)
        updated = await super().update(instance, data)
        await self._enforce_single_active_generation_type(updated)
        return updated

    async def patch(self, config_id: int, obj_in) -> AiModelConfig:
        instance = await self.get(config_id)
        data = self._normalize_payload(obj_in)
        self._validate_generation_payload(data, instance)
        updated = await super().patch(instance, data)
        await self._enforce_single_active_generation_type(updated)
        return updated

    async def remove(self, config_id: int) -> None:
        instance = await self.get(config_id)
        await super().remove(instance)

    async def activate(self, config_id: int) -> AiModelConfig:
        """启用配置；同一生图或视频能力类型自动停用旧项。"""
        instance = await self.get(config_id)
        self._validate_generation_payload({}, instance)
        instance.is_active = True
        await instance.save(update_fields=["is_active", "updated_at"])
        await self._enforce_single_active_generation_type(instance)
        return instance

    async def list_active_image_models(self) -> list[dict]:
        configs = await AiModelConfig.filter(is_active=True).order_by("-updated_at", "-id")
        result = []
        for config in configs:
            if AiTaskTypeEnum.reference_image.value not in self._capabilities(config):
                continue
            if not config.image_model_type:
                continue
            try:
                self._validate_image_payload({}, config)
                capabilities = image_capabilities_for(config.image_model_type)
            except HTTPException:
                continue
            result.append({
                "config_id": config.id,
                "name": config.name,
                "model": config.model,
                "model_type": config.image_model_type,
                "concurrency": config.concurrency,
                "capabilities": capabilities.public_dict(),
            })
        return result

    async def list_active_video_models(self) -> list[dict]:
        configs = await AiModelConfig.filter(is_active=True).order_by("-updated_at", "-id")
        result = []
        for config in configs:
            if AiTaskTypeEnum.video.value not in self._capabilities(config):
                continue
            if not config.video_model_type:
                continue
            try:
                self._validate_video_payload({}, config)
                capabilities = video_capabilities_for(config.video_model_type)
            except HTTPException:
                continue
            result.append({
                "config_id": config.id,
                "name": config.name,
                "model": config.model,
                "model_type": config.video_model_type,
                "concurrency": config.concurrency,
                "capabilities": capabilities.public_dict(),
            })
        return result

    async def list_generation_capabilities(self) -> dict:
        return {
            "image": {
                model_type.value: list(image_capabilities_for(model_type.value).clarities)
                for model_type in ImageModelTypeEnum
            },
            "video": {
                model_type.value: list(video_capabilities_for(model_type.value).resolutions)
                for model_type in VideoGenerationModelTypeEnum
            },
        }

    async def deactivate(self, config_id: int) -> AiModelConfig:
        """停用指定配置，不影响同用途下的其他运行配置。"""
        instance = await self.get(config_id)
        instance.is_active = False
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

    async def get_active(
        self,
        task_type: int,
        config_id: int | None = None,
    ) -> AiModelConfig:
        """获取可用于任务的启用配置；未指定时使用最近启用的一项。"""
        active_configs = await AiModelConfig.filter(is_active=True).order_by(
            "-updated_at",
            "-id",
        )
        if config_id is not None:
            selected = next((item for item in active_configs if item.id == config_id), None)
            if selected is None:
                raise HTTPException(status_code=400, detail="所选模型未启用或已被删除")
            if task_type not in self._capabilities(selected):
                raise HTTPException(status_code=400, detail="所选模型不支持当前生成任务")
            if task_type == AiTaskTypeEnum.reference_image.value:
                self._validate_image_payload({}, selected)
            if task_type == AiTaskTypeEnum.video.value:
                self._validate_video_payload({}, selected)
            return selected
        candidates = [
            item for item in active_configs if task_type in self._capabilities(item)
        ]
        config = None
        for candidate in candidates:
            if task_type == AiTaskTypeEnum.reference_image.value:
                try:
                    self._validate_image_payload({}, candidate)
                except HTTPException:
                    continue
            if task_type == AiTaskTypeEnum.video.value:
                try:
                    self._validate_video_payload({}, candidate)
                except HTTPException:
                    continue
            config = candidate
            break
        if config is None:
            try:
                name = AiTaskTypeEnum(task_type).nickname
            except ValueError:
                name = str(task_type)
            raise HTTPException(
                status_code=404,
                detail=f"请先在「配置」中为「{name}」启用一个模型",
            )
        return config

    async def get_active_with_legacy_fallback(
        self,
        task_type: int,
        legacy_task_type: int,
    ) -> AiModelConfig:
        """优先读取目标能力；未配置时兼容升级前复用的历史能力。"""
        try:
            return await self.get_active(task_type)
        except HTTPException as error:
            if error.status_code != 404:
                raise
        return await self.get_active(legacy_task_type)

    async def get_configured_for_task(
        self,
        task_type: int,
        config_id: int,
    ) -> AiModelConfig:
        """读取任务创建时使用的配置，不要求它仍处于启用状态。

        新任务只能使用启用配置；已有异步任务即使随后被停用，仍需使用原配置查询结果。
        """
        selected = await self.get(config_id)
        if task_type not in self._capabilities(selected):
            raise HTTPException(status_code=400, detail="所选模型不支持当前生成任务")
        if task_type == AiTaskTypeEnum.reference_image.value:
            self._validate_image_payload({}, selected)
        if task_type == AiTaskTypeEnum.video.value:
            self._validate_video_payload({}, selected)
        return selected


ai_model_config_controller = AiModelConfigController()


class GeneralConfigController:
    """管理应用级单例配置。"""

    async def get(self) -> GeneralConfig:
        config, _ = await GeneralConfig.get_or_create(
            id=1,
            defaults={"prompt_language": "en"},
        )
        return config

    async def update(self, obj_in: GeneralConfigUpdate) -> GeneralConfig:
        config = await self.get()
        config.prompt_language = obj_in.prompt_language
        await config.save(update_fields=["prompt_language", "updated_at"])
        return config

    async def get_prompt_language(self) -> str:
        return (await self.get()).prompt_language


general_config_controller = GeneralConfigController()
