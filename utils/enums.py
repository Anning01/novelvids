from enum import IntEnum, StrEnum
from typing import TypeVar

T = TypeVar("T")


def enum_description(enum_cls: type[T]) -> type[T]:
    """生成枚举描述（值=昵称）"""
    enum_cls.__doc__ = ", ".join([f"{m.value}={m.nickname}" for m in enum_cls])
    return enum_cls


class NicknameIntEnum(IntEnum):
    """Enum with nickname and description."""

    def __new__(cls, value, nickname):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.nickname = nickname
        return obj

    @classmethod
    def values(cls):
        return [member.value for member in cls.__members__.values()]


class NicknameStrEnum(StrEnum):
    """Enum with nickname and description."""

    def __new__(cls, value, nickname):
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.nickname = nickname
        return obj


@enum_description
class TaskStatusEnum(NicknameIntEnum):
    pending = 1, "待处理"
    running = 2, "处理中"
    completed = 3, "已完成"
    failed = 4, "处理失败"
    cancelled = 5, "已取消"
    queued = 6, "队列中"


@enum_description
class AssetTypeEnum(NicknameIntEnum):
    """资产类型。"""

    person = 1, "人物"
    scene = 2, "场景"
    item = 3, "物品"

@enum_description
class ImageSourceEnum(NicknameIntEnum):
    """图片来源。"""

    ai = 1, "AI 生成"
    upload = 2, "用户上传"

@enum_description
class WorkflowStatus(NicknameIntEnum):
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

    draft = 1, "草稿 - 刚上传"
    chapters_extracted = 2, "已分章"
    characters_extracted = 3, "已提取角色"
    storyboard_ready = 4, "分镜就绪"
    generating = 5, "生成中"
    completed = 6, "已完成"

    @classmethod
    def get_order(cls) -> list["WorkflowStatus"]:
        """获取工作流顺序。"""
        return [
            cls.draft,
            cls.chapters_extracted,
            cls.characters_extracted,
            cls.storyboard_ready,
            cls.generating,
            cls.completed,
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


@enum_description
class AiTaskTypeEnum(NicknameIntEnum):
    """AI 任务类型。"""

    extraction = 1, "提取任务"
    reference_image = 2, "生成参考图"
    storyboard = 3, "生成分镜"
    video = 4, "生成视频"
