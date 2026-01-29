"""使用 Tortoise ORM 的数据库模型。"""

from enum import StrEnum

from tortoise import fields
from tortoise.models import Model


class TaskStatus(StrEnum):
    """任务执行状态。"""

    PENDING = "pending"  # 待处理
    QUEUED = "queued"  # 已入队
    RUNNING = "running"  # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class WorkflowStatus(StrEnum):
    """小说工作流状态 - 状态机。

    工作流顺序：
    draft -> chapters_extracted -> characters_extracted -> storyboard_ready -> generating -> completed

    状态转换规则：
    - draft: 初始状态，小说刚上传
    - chapters_extracted: 章节已提取（需要 total_chapters > 0）
    - characters_extracted: 角色已提取（需要有 characters）
    - storyboard_ready: 分镜已就绪（需要有 scenes）
    - generating: 正在生成视频
    - completed: 全部完成
    """

    DRAFT = "draft"  # 草稿 - 刚上传
    CHAPTERS_EXTRACTED = "chapters_extracted"  # 已分章
    CHARACTERS_EXTRACTED = "characters_extracted"  # 已提取角色
    STORYBOARD_READY = "storyboard_ready"  # 分镜就绪
    GENERATING = "generating"  # 生成中
    COMPLETED = "completed"  # 已完成

    @classmethod
    def get_order(cls) -> list["WorkflowStatus"]:
        """获取工作流顺序。"""
        return [
            cls.DRAFT,
            cls.CHAPTERS_EXTRACTED,
            cls.CHARACTERS_EXTRACTED,
            cls.STORYBOARD_READY,
            cls.GENERATING,
            cls.COMPLETED,
        ]

    def can_transition_to(self, target: "WorkflowStatus") -> bool:
        """检查是否可以转换到目标状态。"""
        order = self.get_order()
        current_idx = order.index(self)
        target_idx = order.index(target)
        # 只能向前进一步，或者保持原状态
        return target_idx == current_idx or target_idx == current_idx + 1

    def get_next(self) -> "WorkflowStatus | None":
        """获取下一个状态。"""
        order = self.get_order()
        current_idx = order.index(self)
        if current_idx < len(order) - 1:
            return order[current_idx + 1]
        return None


class ChapterWorkflowStatus(StrEnum):
    """章节工作流状态 - 每章独立的处理状态。

    工作流顺序：
    pending -> characters_extracted -> assets_reviewed -> storyboard_ready -> generating -> completed

    每章独立处理，完成后才能进行下一步。
    """

    PENDING = "pending"  # 待处理
    CHARACTERS_EXTRACTED = "characters_extracted"  # 已提取角色/资产
    ASSETS_REVIEWED = "assets_reviewed"  # 资产已审核（图片已准备）
    STORYBOARD_READY = "storyboard_ready"  # 分镜就绪
    GENERATING = "generating"  # 生成中
    COMPLETED = "completed"  # 已完成

    @classmethod
    def get_order(cls) -> list["ChapterWorkflowStatus"]:
        """获取工作流顺序。"""
        return [
            cls.PENDING,
            cls.CHARACTERS_EXTRACTED,
            cls.ASSETS_REVIEWED,
            cls.STORYBOARD_READY,
            cls.GENERATING,
            cls.COMPLETED,
        ]

    def can_transition_to(self, target: "ChapterWorkflowStatus") -> bool:
        """检查是否可以转换到目标状态。"""
        order = self.get_order()
        current_idx = order.index(self)
        target_idx = order.index(target)
        # 允许前进一步或后退一步
        return abs(target_idx - current_idx) <= 1

    def get_next(self) -> "ChapterWorkflowStatus | None":
        """获取下一个状态。"""
        order = self.get_order()
        current_idx = order.index(self)
        if current_idx < len(order) - 1:
            return order[current_idx + 1]
        return None

    def get_previous(self) -> "ChapterWorkflowStatus | None":
        """获取上一个状态。"""
        order = self.get_order()
        current_idx = order.index(self)
        if current_idx > 0:
            return order[current_idx - 1]
        return None


class AssetType(StrEnum):
    """资产类型。"""

    PERSON = "person"  # 人物
    SCENE = "scene"  # 场景
    ITEM = "item"  # 物品


class ImageSource(StrEnum):
    """图片来源。"""

    AI = "ai"  # AI 生成
    UPLOAD = "upload"  # 用户上传


class ChapterSource(StrEnum):
    """章节来源。"""

    EXTRACTED = "extracted"  # 从小说内容提取
    MANUAL = "manual"  # 手动创建


class BaseModel(Model):
    """包含通用字段的基础模型。"""

    id = fields.UUIDField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True


class UserModel(BaseModel):
    """用户数据库模型。"""

    username = fields.CharField(max_length=50, unique=True, index=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    hashed_password = fields.CharField(max_length=255)
    is_active = fields.BooleanField(default=True)
    is_superuser = fields.BooleanField(default=False)
    balance = fields.DecimalField(max_digits=12, decimal_places=4, default=0)
    metadata = fields.JSONField(default=dict)

    novels: fields.ReverseRelation["NovelModel"]
    usage_records: fields.ReverseRelation["UsageRecordModel"]

    class Meta:
        table = "users"


class NovelModel(BaseModel):
    """小说数据库模型。"""

    title = fields.CharField(max_length=255, index=True)
    content = fields.TextField(null=True)  # 改为可选，支持手动创建章节
    chapter_source = fields.CharEnumField(ChapterSource, default=ChapterSource.EXTRACTED)
    author = fields.CharField(max_length=255, null=True)
    user: fields.ForeignKeyRelation[UserModel] = fields.ForeignKeyField(
        "models.UserModel",
        related_name="novels",
        on_delete=fields.CASCADE,
    )
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)
    workflow_status = fields.CharEnumField(WorkflowStatus, default=WorkflowStatus.DRAFT, index=True)
    total_chapters = fields.IntField(default=0)
    processed_chapters = fields.IntField(default=0)
    metadata = fields.JSONField(default=dict)

    chapters: fields.ReverseRelation["ChapterModel"]
    assets: fields.ReverseRelation["AssetModel"]
    videos: fields.ReverseRelation["VideoModel"]

    class Meta:
        table = "novels"

    def can_extract_chapters(self) -> bool:
        """检查是否可以提取章节。"""
        return self.workflow_status == WorkflowStatus.DRAFT and bool(self.content)

    def can_extract_characters(self) -> bool:
        """检查是否可以提取角色/资产。只要有章节就可以。"""
        return self.total_chapters > 0

    def can_create_storyboard(self) -> bool:
        """检查是否可以创建分镜。"""
        return self.workflow_status in (WorkflowStatus.CHAPTERS_EXTRACTED, WorkflowStatus.CHARACTERS_EXTRACTED) and self.total_chapters > 0

    def can_generate_video(self) -> bool:
        """检查是否可以生成视频。"""
        return self.workflow_status == WorkflowStatus.STORYBOARD_READY

    async def advance_workflow(self, target_status: WorkflowStatus) -> bool:
        """尝试推进工作流状态。

        Args:
            target_status: 目标状态

        Returns:
            是否成功推进
        """
        if self.workflow_status.can_transition_to(target_status):
            self.workflow_status = target_status
            await self.save(update_fields=["workflow_status", "updated_at"])
            return True
        return False


class ChapterModel(BaseModel):
    """章节数据库模型。"""

    novel: fields.ForeignKeyRelation[NovelModel] = fields.ForeignKeyField(
        "models.NovelModel",
        related_name="chapters",
        on_delete=fields.CASCADE,
    )
    number = fields.IntField(index=True)
    title = fields.CharField(max_length=255)
    content = fields.TextField()
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)
    workflow_status = fields.CharEnumField(
        ChapterWorkflowStatus, default=ChapterWorkflowStatus.PENDING, index=True
    )
    scene_count = fields.IntField(default=0)
    metadata = fields.JSONField(default=dict)

    scenes: fields.ReverseRelation["SceneModel"]
    asset_appearances: fields.ReverseRelation["ChapterAssetModel"]

    class Meta:
        table = "chapters"
        unique_together = (("novel", "number"),)

    def can_extract_characters(self) -> bool:
        """检查是否可以提取角色。"""
        return self.workflow_status == ChapterWorkflowStatus.PENDING

    def can_create_storyboard(self) -> bool:
        """检查是否可以创建分镜。"""
        return self.workflow_status == ChapterWorkflowStatus.CHARACTERS_EXTRACTED

    def can_generate_video(self) -> bool:
        """检查是否可以生成视频。"""
        return self.workflow_status == ChapterWorkflowStatus.STORYBOARD_READY


class AssetModel(BaseModel):
    """通用资产模型 - 人物/场景/物品。

    统一管理所有类型的资产，支持：
    - 三种类型：person（人物）、scene（场景）、item（物品）
    - 图片资产：主图 + 2张可选角度图
    - AI 生成或用户上传
    - 全局资产或单章资产
    """

    novel: fields.ForeignKeyRelation[NovelModel] = fields.ForeignKeyField(
        "models.NovelModel",
        related_name="assets",
        on_delete=fields.CASCADE,
    )
    asset_type = fields.CharEnumField(AssetType, index=True)
    canonical_name = fields.CharField(max_length=100, index=True)
    aliases = fields.JSONField(default=list)  # 别名列表 ["张三", "小张"]

    # 描述信息
    description = fields.TextField(null=True)  # 详细描述 (中文)
    base_traits = fields.TextField(null=True)  # 固有特征 (英文, 用于 prompt)

    # 图片资产
    main_image = fields.CharField(max_length=500, null=True)  # 主图路径/URL
    angle_image_1 = fields.CharField(max_length=500, null=True)  # 角度图1
    angle_image_2 = fields.CharField(max_length=500, null=True)  # 角度图2
    image_source = fields.CharEnumField(ImageSource, default=ImageSource.AI)

    # 状态追踪
    is_global = fields.BooleanField(default=True)  # 是否全局资产
    source_chapters = fields.JSONField(default=list)  # 出现的章节列表 [1, 3, 5]
    last_updated_chapter = fields.IntField(default=0)

    # 元数据
    metadata = fields.JSONField(default=dict)

    # 反向关联
    chapter_appearances: fields.ReverseRelation["ChapterAssetModel"]

    class Meta:
        table = "assets"
        unique_together = (("novel", "asset_type", "canonical_name"),)


class ChapterAssetModel(BaseModel):
    """章节与资产的关联，记录章节级别的状态变化。

    用于追踪同一资产在不同章节中的不同状态，
    例如：角色换装、场景变化等。
    """

    chapter: fields.ForeignKeyRelation[ChapterModel] = fields.ForeignKeyField(
        "models.ChapterModel",
        related_name="asset_appearances",
        on_delete=fields.CASCADE,
    )
    asset: fields.ForeignKeyRelation[AssetModel] = fields.ForeignKeyField(
        "models.AssetModel",
        related_name="chapter_appearances",
        on_delete=fields.CASCADE,
    )

    # 章节特定状态
    state_description = fields.TextField(null=True)  # 该章节的状态描述
    state_traits = fields.TextField(null=True)  # 该章节的特征 (英文 prompt)

    # 位置信息 (用于分镜)
    appearances = fields.JSONField(default=list)  # [{"line": 10, "context": "..."}]

    # 元数据
    metadata = fields.JSONField(default=dict)

    class Meta:
        table = "chapter_assets"
        unique_together = (("chapter", "asset"),)


class SceneModel(BaseModel):
    """场景数据库模型，表示单个分镜/镜头。"""

    chapter: fields.ForeignKeyRelation[ChapterModel] = fields.ForeignKeyField(
        "models.ChapterModel",
        related_name="scenes",
        on_delete=fields.CASCADE,
    )
    sequence = fields.IntField(index=True)
    description = fields.TextField()
    dialogue = fields.TextField(null=True)
    speaker: fields.ForeignKeyRelation[AssetModel] | None = fields.ForeignKeyField(
        "models.AssetModel",
        related_name="spoken_scenes",
        on_delete=fields.SET_NULL,
        null=True,
    )
    prompt = fields.TextField(null=True)
    negative_prompt = fields.TextField(null=True)
    image_url = fields.CharField(max_length=500, null=True)
    audio_url = fields.CharField(max_length=500, null=True)
    duration = fields.FloatField(default=0.0)
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)
    metadata = fields.JSONField(default=dict)

    class Meta:
        table = "scenes"
        unique_together = (("chapter", "sequence"),)


class VideoModel(BaseModel):
    """视频数据库模型。"""

    novel: fields.ForeignKeyRelation[NovelModel] = fields.ForeignKeyField(
        "models.NovelModel",
        related_name="videos",
        on_delete=fields.CASCADE,
    )
    chapter: fields.ForeignKeyRelation[ChapterModel] | None = fields.ForeignKeyField(
        "models.ChapterModel",
        related_name="videos",
        on_delete=fields.SET_NULL,
        null=True,
    )
    title = fields.CharField(max_length=255)
    url = fields.CharField(max_length=500, null=True)
    duration = fields.FloatField(default=0.0)
    resolution = fields.CharField(max_length=20, default="1920x1080")
    fps = fields.IntField(default=24)
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)
    metadata = fields.JSONField(default=dict)

    class Meta:
        table = "videos"


class UsageRecordModel(BaseModel):
    """使用记录模型，用于计费。"""

    user: fields.ForeignKeyRelation[UserModel] = fields.ForeignKeyField(
        "models.UserModel",
        related_name="usage_records",
        on_delete=fields.CASCADE,
    )
    resource_type = fields.CharField(max_length=50, index=True)
    quantity = fields.FloatField()
    unit_cost = fields.DecimalField(max_digits=10, decimal_places=6)
    total_cost = fields.DecimalField(max_digits=12, decimal_places=4)
    description = fields.CharField(max_length=255, null=True)
    metadata = fields.JSONField(default=dict)

    class Meta:
        table = "usage_records"


class ComfyUIWorkflowModel(BaseModel):
    """ComfyUI 工作流配置模型。"""

    name = fields.CharField(max_length=100, unique=True, index=True)
    description = fields.TextField(null=True)
    workflow_json = fields.JSONField()
    category = fields.CharField(max_length=50, default="general", index=True)
    is_default = fields.BooleanField(default=False)
    metadata = fields.JSONField(default=dict)

    class Meta:
        table = "comfyui_workflows"


class ExtractionTaskType(StrEnum):
    """提取任务类型。"""

    PERSON = "person"  # 人物提取
    SCENE = "scene"  # 场景提取
    ITEM = "item"  # 物品提取


class ExtractionTaskModel(BaseModel):
    """资产提取任务模型 - 跟踪后台提取任务进度。

    每次提取操作创建一个任务记录，支持：
    - 单独提取 person/scene/item
    - 进度追踪 (0-100)
    - 超时控制和重试
    - 结果缓存
    """

    chapter: fields.ForeignKeyRelation["ChapterModel"] = fields.ForeignKeyField(
        "models.ChapterModel",
        related_name="extraction_tasks",
        on_delete=fields.CASCADE,
    )
    task_type = fields.CharEnumField(ExtractionTaskType, index=True)
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)

    # 进度追踪
    progress = fields.IntField(default=0)  # 0-100
    message = fields.CharField(max_length=255, null=True)  # 当前步骤描述

    # 超时和重试
    retry_count = fields.IntField(default=0)
    max_retries = fields.IntField(default=3)
    timeout_seconds = fields.IntField(default=120)  # 2分钟超时

    # 结果
    result = fields.JSONField(null=True)  # 提取结果
    error = fields.TextField(null=True)  # 错误信息

    # 时间追踪
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "extraction_tasks"
        # 每个章节同类型任务只能有一个进行中的
        indexes = [("chapter_id", "task_type", "status")]


class StoryboardTaskModel(BaseModel):
    """分镜生成任务模型 - 跟踪后台分镜生成任务进度。

    每次分镜生成操作创建一个任务记录，支持：
    - 进度追踪 (0-100)
    - 超时控制和重试
    - 结果缓存
    """

    chapter: fields.ForeignKeyRelation["ChapterModel"] = fields.ForeignKeyField(
        "models.ChapterModel",
        related_name="storyboard_tasks",
        on_delete=fields.CASCADE,
    )
    chapter_id: int  # 类型提示，由 Tortoise ORM 自动生成
    status = fields.CharEnumField(TaskStatus, default=TaskStatus.PENDING, index=True)

    # 生成参数
    target_platform = fields.CharField(max_length=50, default="veo")
    max_shot_duration = fields.FloatField(default=8.0)
    style_preset = fields.CharField(max_length=50, default="cinematic")
    aspect_ratio = fields.CharField(max_length=20, default="16:9")
    include_audio = fields.BooleanField(default=True)

    # 进度追踪
    progress = fields.IntField(default=0)  # 0-100
    message = fields.CharField(max_length=255, null=True)  # 当前步骤描述

    # 超时和重试
    retry_count = fields.IntField(default=0)
    max_retries = fields.IntField(default=3)
    timeout_seconds = fields.IntField(default=180)  # 3分钟超时

    # 结果
    result = fields.JSONField(null=True)  # 生成的分镜数据
    error = fields.TextField(null=True)  # 错误信息

    # 时间追踪
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "storyboard_tasks"
        indexes = [("chapter_id", "status")]
