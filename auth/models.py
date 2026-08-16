"""鉴权与团队相关数据模型（仅在 AUTH_ENABLED=true 时注册到 Tortoise）。"""

from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TeamRoleEnum, UserStatusEnum


class User(AbstractBaseModel):
    """用户表。微信扫码登录（二期）接入后 unionid/openid 由对应 Provider 填充。"""

    username = fields.CharField(
        max_length=100, unique=True, description="登录用户名（唯一）"
    )
    password_hash = fields.CharField(
        max_length=255, description="密码哈希（pbkdf2_sha256）"
    )
    nickname = fields.CharField(max_length=100, default="", description="昵称")
    avatar_url = fields.CharField(
        max_length=500, default="", description="头像地址"
    )
    unionid = fields.CharField(max_length=64, null=True, description="微信 unionid")
    openid = fields.CharField(max_length=64, null=True, description="微信 openid")
    is_super_admin = fields.BooleanField(
        default=False, db_index=True, description="是否平台超级管理员"
    )
    status = fields.IntField(
        default=UserStatusEnum.active.value,
        description="账号状态：0 停用 / 1 正常",
    )

    class Meta:
        table = "users"
        table_description = "用户表"

    def __str__(self):
        return f"{self.username}({self.nickname or '-'})"


class Team(AbstractBaseModel):
    """团队表。余额与模型配置来源（官方/自定义）见 P5/P6。"""

    name = fields.CharField(max_length=100, unique=True, description="团队名称")
    balance = fields.DecimalField(
        max_digits=18, decimal_places=6, default=0, description="团队余额（元）"
    )
    model_config_source = fields.CharField(
        max_length=16,
        default="official",
        description="模型配置来源：official 官方配置 / custom 团队自定义",
    )
    status = fields.IntField(
        default=1, description="团队状态：0 停用 / 1 正常"
    )
    member_limit = fields.IntField(
        null=True, description="成员人数上限；NULL 表示不限"
    )
    owner_user_id = fields.IntField(
        null=True, description="团队所有人 User.id（创建团队时指定，自动成为团队管理员）"
    )

    class Meta:
        table = "teams"
        table_description = "团队表"

    def __str__(self):
        return self.name


class TeamMember(AbstractBaseModel):
    """团队成员关系表。一个用户可属于多个团队（侧边栏选择器切换当前团队）。"""

    team = fields.ForeignKeyField(
        "models.Team", related_name="members", on_delete=fields.CASCADE,
        description="所属团队",
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="memberships", on_delete=fields.CASCADE,
        description="成员用户",
    )
    role = fields.CharField(
        max_length=16,
        default=TeamRoleEnum.creator.value,
        description="团队内角色：admin/creator/viewer",
    )
    status = fields.IntField(
        default=1, description="成员状态：0 已禁用 / 1 正常"
    )
    total_cost = fields.DecimalField(
        max_digits=18, decimal_places=6, default=0, description="累计历史消耗金额（元）"
    )
    cost_limit = fields.DecimalField(
        max_digits=18, decimal_places=6, null=True,
        description="个人累计消费限额（元）；NULL 表示不限",
    )

    class Meta:
        table = "team_members"
        table_description = "团队成员表"
        unique_together = (("team_id", "user_id"),)

    def __str__(self):
        return f"{self.user_id}@{self.team_id}:{self.role}"


class TeamInvite(AbstractBaseModel):
    """团队邀请链接：24 小时有效，可多人使用，直到过期或被删除。"""

    token = fields.CharField(max_length=64, unique=True, description="邀请令牌")
    team = fields.ForeignKeyField(
        "models.Team", related_name="invites", on_delete=fields.CASCADE,
        description="目标团队",
    )
    role = fields.CharField(
        max_length=16,
        default=TeamRoleEnum.creator.value,
        description="加入后的角色",
    )
    created_by = fields.IntField(null=True, description="创建人 User.id")
    expires_at = fields.DatetimeField(description="过期时间")
    used_count = fields.IntField(default=0, description="已加入人数")

    class Meta:
        table = "team_invites"
        table_description = "团队邀请表"

    def __str__(self):
        return f"invite:{self.token[:8]}@{self.team_id}"


class UserSession(AbstractBaseModel):
    """登录会话表。库存 token 哈希，可吊销、可过期。"""

    token_hash = fields.CharField(
        max_length=64, unique=True, description="会话令牌哈希"
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="sessions", on_delete=fields.CASCADE,
        description="会话所属用户",
    )
    expires_at = fields.DatetimeField(description="过期时间")
    last_seen_at = fields.DatetimeField(null=True, description="最近活跃时间")

    class Meta:
        table = "user_sessions"
        table_description = "登录会话表"

    def __str__(self):
        return f"session:{self.user_id}"


class BalanceTransaction(AbstractBaseModel):
    """团队余额流水表：充值/消费/调整，不可变。balance_after 冗余用于对账。"""

    team = fields.ForeignKeyField(
        "models.Team",
        related_name="balance_transactions",
        on_delete=fields.CASCADE,
        description="所属团队",
    )
    change_amount = fields.DecimalField(
        max_digits=18, decimal_places=6, description="变动金额（正=入账，负=出账）"
    )
    balance_after = fields.DecimalField(
        max_digits=18, decimal_places=6, description="变动后余额"
    )
    type = fields.CharField(
        max_length=16, description="流水类型：topup/consume/adjust"
    )
    usage_record_id = fields.IntField(null=True, description="关联计费流水 ID")
    operator_user_id = fields.IntField(
        null=True, description="操作人 User.id（充值/调整）"
    )
    note = fields.CharField(max_length=255, default="", description="备注")

    class Meta:
        table = "balance_transactions"
        table_description = "团队余额流水表"

    def __str__(self):
        return f"{self.type}:{self.change_amount}->{self.balance_after}"
