"""模型配置作用域解析：团队自定义优先，官方配置兜底。

运行时唯一事实来源：
- `team_id=None`（超管 / 关闭开关）：仅官方配置参与解析；
- `team_id=X`：按团队「模型配置来源」模式决定——
  - `official`：仅使用官方启用配置；
  - `custom`（默认历史行为）：团队启用配置优先，该任务类型无团队配置时回退官方。
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

    # 团队「模型配置来源」为 official 时，仅用官方配置（含官方折扣），
    # 忽略团队自有配置，使开关真正生效。
    from auth.models import Team

    team = await Team.get_or_none(id=team_id)
    if team is not None and team.model_config_source == "official":
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
