from fastapi import HTTPException

from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum


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

    async def _ensure_single_active(self, task_types: set[int], exclude_id: int | None = None):
        """确保每个能力用途下只有一个启用配置。"""
        query = AiModelConfig.filter(is_active=True)
        if exclude_id is not None:
            query = query.exclude(id=exclude_id)
        active_configs = await query
        conflicting_ids = [
            config.id for config in active_configs
            if self._capabilities(config) & task_types
        ]
        if conflicting_ids:
            await AiModelConfig.filter(id__in=conflicting_ids).update(is_active=False)

    async def create(self, obj_in: AiModelConfigCreate, **kwargs) -> AiModelConfig:
        instance = await super().create(self._normalize_payload(obj_in), **kwargs)
        if instance.is_active:
            await self._ensure_single_active(self._capabilities(instance), exclude_id=instance.id)
        return instance

    async def update(self, config_id: int, obj_in: AiModelConfigUpdate) -> AiModelConfig:
        instance = await self.get(config_id)
        instance = await super().update(instance, self._normalize_payload(obj_in))
        if instance.is_active:
            await self._ensure_single_active(self._capabilities(instance), exclude_id=instance.id)
        return instance

    async def patch(self, config_id: int, obj_in) -> AiModelConfig:
        instance = await self.get(config_id)
        instance = await super().patch(instance, self._normalize_payload(obj_in))
        if instance.is_active:
            await self._ensure_single_active(self._capabilities(instance), exclude_id=instance.id)
        return instance

    async def remove(self, config_id: int) -> None:
        instance = await self.get(config_id)
        await super().remove(instance)

    async def activate(self, config_id: int) -> AiModelConfig:
        """启用指定配置，同类型下其他配置自动禁用。"""
        instance = await self.get(config_id)
        await self._ensure_single_active(self._capabilities(instance), exclude_id=config_id)
        instance.is_active = True
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

    async def get_active(self, task_type: int) -> AiModelConfig:
        """获取某任务类型当前启用的配置。"""
        active_configs = await AiModelConfig.filter(is_active=True)
        config = next(
            (item for item in active_configs if task_type in self._capabilities(item)),
            None,
        )
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
