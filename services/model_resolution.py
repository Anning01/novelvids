"""模型配置作用域解析：团队自定义优先，官方配置兜底。

运行时唯一事实来源：
- `team_id=None`（超管 / 关闭开关）：仅官方配置参与解析；
- `team_id=X`：团队启用的自定义配置优先；该任务类型无团队配置时回退官方启用配置。
"""

from models.config import AiModelConfig


async def resolve_scope_configs(
    task_type: int,
    team_id: int | None = None,
    capability_filter=None,
) -> list[AiModelConfig]:
    """返回按任务类型解析后的启用配置候选（按最近更新倒序）。

    `capability_filter(config) -> bool` 由调用方注入（控制器内聚其能力校验）。
    """
    official = await AiModelConfig.filter(is_active=True, team_id=None).order_by(
        "-updated_at", "-id"
    )
    official = [c for c in official if task_type in _task_capabilities(c)]
    if capability_filter is not None:
        official = [c for c in official if capability_filter(c)]

    if team_id is None:
        return official

    team_configs = await AiModelConfig.filter(
        is_active=True, team_id=team_id
    ).order_by("-updated_at", "-id")
    team_configs = [
        c for c in team_configs if task_type in _task_capabilities(c)
    ]
    if capability_filter is not None:
        team_configs = [c for c in team_configs if capability_filter(c)]
    return team_configs or official


def _task_capabilities(config: AiModelConfig) -> list[int]:
    """兼容旧数据：task_types 缺失时回退主任务类型。"""
    task_types = config.task_types or []
    if not task_types and config.task_type:
        return [config.task_type]
    return task_types
