from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import AiTaskTypeEnum
from utils.image_protocol import ImageApiProtocol


class AiModelConfig(AbstractBaseModel):
    """AI 模型配置表 - 每种任务类型可配置并同时启用多个。"""

    task_type = fields.IntField(
        db_index=True,
        description="主任务类型（兼容旧数据）",
    )
    task_types = fields.JSONField(
        default=list,
        description="模型支持的任务类型列表",
    )
    name = fields.CharField(
        max_length=100,
        description="配置名称，如 deepseek-v3、gpt-4o",
    )
    base_url = fields.CharField(
        max_length=500,
        description="API 地址",
    )
    api_key = fields.CharField(
        max_length=500,
        description="API Key",
    )
    model = fields.CharField(
        max_length=200,
        description="模型名称",
    )
    api_protocol = fields.CharField(
        max_length=40,
        default=ImageApiProtocol.openai_compatible.value,
        description="接口协议，生图任务用于选择供应商请求适配器",
    )
    image_model_type = fields.CharField(
        max_length=40,
        null=True,
        description="生图模型能力类型；非生图配置留空",
    )
    video_model_type = fields.CharField(
        max_length=40,
        null=True,
        description="视频生成模型能力类型；非视频配置留空",
    )
    is_active = fields.BooleanField(
        default=False,
        db_index=True,
        description="是否启用",
    )
    concurrency = fields.IntField(
        default=1,
        description="并发数",
    )
    supports_json_output = fields.BooleanField(
        default=False,
        description="是否支持 response_format=json_object",
    )
    max_context_characters = fields.IntField(
        null=True,
        description="四层业务消息允许的最大总字符数；留空表示不预检",
    )
    pricing = fields.JSONField(
        null=True,
        description="计费费用模块，按任务类型分 text/image/video 三种结构",
    )

    class Meta:
        table = "ai_model_configs"
        table_description = "AI 模型配置表"
        unique_together = (("task_type", "name"),)

    def __str__(self):
        status = "✓" if self.is_active else "✗"
        return f"[{status}] {self.name}({AiTaskTypeEnum(self.task_type).nickname})"


class GeneralConfig(AbstractBaseModel):
    """应用级通用配置。固定使用 id=1 的单例记录。"""

    prompt_language = fields.CharField(
        max_length=8,
        default="en",
        description="新生成提示词使用的语言：zh/en",
    )

    class Meta:
        table = "general_configs"
        table_description = "应用级通用配置表"
