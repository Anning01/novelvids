"""团队余额 / 成员 / 邀请 / 团队管理 API。仅在 AUTH_ENABLED=true 时注册。

- 团队管理员：余额与流水、管理本团队成员、生成邀请链接
- 超级管理员：任意团队充值与管理、全部团队 CRUD（含人员上限）
- 成员加入团队的唯一方式：24 小时有效的邀请链接（新用户注册或老用户加入）
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.deps import AuthContext, get_current_user, require_roles, require_super_admin
from auth.models import User
from controllers.team import team_controller
from schemas.team import (
    BalanceTopUpIn,
    BalanceTransactionOut,
    InviteOut,
    MemberLimitIn,
    MemberOut,
    MemberPatchIn,
    MemberResetPasswordIn,
    TeamBalanceOut,
    TeamCreateIn,
    TeamOut,
    TeamPatchIn,
)
from utils.page import get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

_ADMIN = Depends(require_roles("admin"))
_SUPER = Depends(require_super_admin)


def _team_id_or_own(ctx: AuthContext, team_id: int | None) -> int:
    """超管可指定团队；团队管理员固定本人团队。"""
    if ctx.is_super_admin:
        if team_id is None:
            raise HTTPException(status_code=400, detail="请指定 team_id")
        return team_id
    return ctx.team_id


def _operator_id(ctx: AuthContext) -> int | None:
    return ctx.user.id if ctx.user else None


# ---------------------------------------------------------------- 余额


@router.get(
    "/balance",
    summary="查询团队余额",
    response_model=ResponseSchema[TeamBalanceOut],
)
async def get_team_balance(
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    return ResponseSchema(
        data=await team_controller.balance(_team_id_or_own(ctx, team_id))
    )


@router.post(
    "/balance/topup",
    summary="团队余额充值（仅超级管理员）",
    response_model=ResponseSchema[TeamBalanceOut],
)
async def top_up_team_balance(
    payload: BalanceTopUpIn,
    ctx: AuthContext = _SUPER,
):
    return ResponseSchema(
        data=await team_controller.top_up(
            payload.team_id,
            payload.amount,
            operator_user_id=_operator_id(ctx),
            note=payload.note,
        )
    )


@router.get(
    "/balance/transactions",
    summary="团队余额流水",
    response_model=ResponseSchema[PaginationResponse[BalanceTransactionOut]],
)
async def get_balance_transactions(
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
    params=Depends(get_list_params),
):
    target = _team_id_or_own(ctx, team_id)
    return ResponseSchema(
        data=await team_controller.transactions(target, params.page, params.page_size)
    )


# ---------------------------------------------------------------- 邀请链接


@router.post(
    "/invites",
    summary="生成邀请链接（24 小时有效）",
    response_model=ResponseSchema[InviteOut],
)
async def create_invite(
    role: str = Query(default="creator"),
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    return ResponseSchema(
        data=await team_controller.create_invite(
            _team_id_or_own(ctx, team_id), role, _operator_id(ctx)
        )
    )


@router.get(
    "/invites/{token}",
    summary="邀请链接信息（公开，供邀请页展示）",
    response_model=ResponseSchema[InviteOut],
)
async def get_invite_info(token: str):
    return ResponseSchema(data=await team_controller.invite_info(token))


@router.post(
    "/invites/{token}/join",
    summary="经邀请链接加入团队（需登录）",
    response_model=ResponseSchema[InviteOut],
)
async def join_invite(
    token: str,
    user: User = Depends(get_current_user),
):
    return ResponseSchema(
        data={
            **(await team_controller.join_invite(token, user)),
            "token": token,
            "expires_at": "",
        }
    )


# ---------------------------------------------------------------- 成员


@router.get(
    "/members",
    summary="团队成员列表（分页，含累计消耗与限额）",
    response_model=ResponseSchema[PaginationResponse[MemberOut]],
)
async def list_members(
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
    params=Depends(get_list_params),
):
    return ResponseSchema(
        data=await team_controller.members(
            _team_id_or_own(ctx, team_id), params.page, params.page_size
        )
    )


@router.patch(
    "/members/{user_id}",
    summary="调整成员角色或禁用/启用成员",
    response_model=ResponseSchema[MemberOut],
)
async def update_member(
    user_id: int,
    payload: MemberPatchIn,
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    return ResponseSchema(
        data=await team_controller.update_member(
            _team_id_or_own(ctx, team_id),
            user_id,
            _operator_id(ctx),
            role=payload.role,
            status=payload.status,
        )
    )


@router.put(
    "/members/{user_id}/limit",
    summary="设置成员消费限额（null 为不限）",
    response_model=ResponseSchema[MemberOut],
)
async def set_member_limit(
    user_id: int,
    payload: MemberLimitIn,
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    return ResponseSchema(
        data=await team_controller.set_member_limit(
            _team_id_or_own(ctx, team_id), user_id, payload.cost_limit
        )
    )


@router.post(
    "/members/{user_id}/reset-password",
    summary="重置成员密码",
    response_model=ResponseSchema[None],
)
async def reset_member_password(
    user_id: int,
    payload: MemberResetPasswordIn,
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    await team_controller.reset_member_password(
        _team_id_or_own(ctx, team_id), user_id, payload.new_password
    )
    return ResponseSchema(data=None, message="密码已重置")


@router.delete(
    "/members/{user_id}",
    summary="移除成员（踢出）",
    response_model=ResponseSchema[None],
)
async def remove_member(
    user_id: int,
    ctx: AuthContext = _ADMIN,
    team_id: int | None = Query(default=None, ge=1),
):
    await team_controller.remove_member(
        _team_id_or_own(ctx, team_id), user_id, _operator_id(ctx)
    )
    return ResponseSchema(data=None, message="已移除成员")


# ---------------------------------------------------------------- 团队（超管）


@router.get(
    "/teams",
    summary="团队列表（仅超级管理员）",
    response_model=ResponseSchema[PaginationResponse[TeamOut]],
)
async def list_teams(
    _: AuthContext = _SUPER,
    params=Depends(get_list_params),
):
    return ResponseSchema(
        data=await team_controller.teams(params.page, params.page_size)
    )


@router.post(
    "/teams",
    summary="创建团队（仅超级管理员，必须指定所有人）",
    response_model=ResponseSchema[TeamOut],
)
async def create_team(payload: TeamCreateIn, _: AuthContext = _SUPER):
    team = await team_controller.create_team(
        payload.name, payload.owner_user_id, payload.member_limit
    )
    from auth.models import User as AuthUser

    owner = await AuthUser.get_or_none(id=team.owner_user_id)
    return ResponseSchema(
        data={
            "id": team.id,
            "name": team.name,
            "balance": team.balance,
            "model_config_source": team.model_config_source,
            "status": team.status,
            "member_limit": team.member_limit,
            "owner_user_id": team.owner_user_id,
            "owner_username": owner.username if owner else "",
            "member_count": 1,
        }
    )


@router.patch(
    "/teams/{team_id}",
    summary="修改团队（仅超级管理员）",
    response_model=ResponseSchema[TeamOut],
)
async def patch_team(
    team_id: int, payload: TeamPatchIn, _: AuthContext = _SUPER
):
    return ResponseSchema(
        data=await team_controller.update_team(
            team_id, payload.name, payload.status, payload.member_limit
        )
    )
