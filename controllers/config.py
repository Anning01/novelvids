from fastapi import HTTPException

from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum


class AiModelConfigController(CRUDBase[AiModelConfig, AiModelConfigCreate, AiModelConfigUpdate]):
    def __init__(self):
        super().__init__(model=AiModelConfig)

    async def _ensure_single_active(self, task_type: int, exclude_id: int | None = None):
        """确保同 task_type 下只有一个 is_active=True。"""
        query = AiModelConfig.filter(task_type=task_type, is_active=True)
        if exclude_id is not None:
            query = query.exclude(id=exclude_id)
        await query.update(is_active=False)

    async def create(self, obj_in: AiModelConfigCreate, **kwargs) -> AiModelConfig:
        instance = await super().create(obj_in, **kwargs)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def update(self, config_id: int, obj_in: AiModelConfigUpdate) -> AiModelConfig:
        instance = await self.get(config_id)
        instance = await super().update(instance, obj_in)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def patch(self, config_id: int, obj_in) -> AiModelConfig:
        instance = await self.get(config_id)
        instance = await super().patch(instance, obj_in)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def remove(self, config_id: int) -> None:
        instance = await self.get(config_id)
        await super().remove(instance)

    async def activate(self, config_id: int) -> AiModelConfig:
        """启用指定配置，同类型下其他配置自动禁用。"""
        instance = await self.get(config_id)
        await self._ensure_single_active(instance.task_type, exclude_id=config_id)
        instance.is_active = True
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

    async def get_active(self, task_type: int) -> AiModelConfig:
        """获取某任务类型当前启用的配置。"""
        config = await AiModelConfig.get_or_none(task_type=task_type, is_active=True)
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


ai_model_config_controller = AiModelConfigController()
