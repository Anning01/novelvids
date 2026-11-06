"""团队余额 / 成员 / 邀请 / 团队管理 API。仅在 AUTH_ENABLED=true 时注册。

- 团队管理员：余额与流水、管理本团队成员、生成邀请链接
- 超级管理员：任意团队充值与管理、全部团队 CRUD（含人员上限）
- 成员加入团队的唯一方式：24 小时有效的邀请链接（新用户注册或老用户加入）
"""

from utils.messages import localized_message

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from auth.deps import AuthContext, get_auth_context, get_current_user, require_roles, require_super_admin
from auth.models import Team, TeamMember, User
from auth.api import password_provider
from config import settings
from controllers.team import team_controller
from schemas.team import (
    BalanceTopUpIn,
    BalanceTransactionOut,
    InviteOut,
    MemberLimitIn,
    MemberOut,
    MemberPaginationResponse,
    MemberPatchIn,
    MemberResetPasswordIn,
    RechargeCreateIn,
    RechargeOrderAdminOut,
    RechargeOrderDetailOut,
    RechargeOrderOut,
    RefundOrderIn,
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
    """超管可指定团队；未指定时回退当前选中的团队；团队管理员固定本人团队。"""
    if ctx.is_super_admin:
        target = team_id or ctx.team_id
        if target is None:
            raise HTTPException(status_code=400, detail=localized_message('请指定 team_id'))
        return target
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


@router.post(
    "/balance/recharge",
    summary="创建团队充值订单（微信支付 Native 扫码）",
    response_model=ResponseSchema[RechargeOrderOut],
)
async def create_recharge_order(
    payload: RechargeCreateIn,
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.user:
        raise HTTPException(401, localized_message("需要登录"))

    if not ctx.is_super_admin:
        membership = await TeamMember.filter(
            team_id=payload.team_id,
            user_id=ctx.user.id,
            status=1,
        ).first()
        if membership is None:
            raise HTTPException(403, localized_message("仅团队成员或超级管理员可为此团队充值"))

    order = await team_controller.create_recharge(
        team_id=payload.team_id,
        user_id=ctx.user.id,
        amount=payload.amount,
        note=payload.note,
    )
    return ResponseSchema(data=order)


@router.get(
    "/balance/recharge/{out_trade_no}",
    summary="查询充值订单状态",
    response_model=ResponseSchema[RechargeOrderDetailOut],
)
async def get_recharge_order_status(
    out_trade_no: str,
    ctx: AuthContext = Depends(get_auth_context),
):
    user_id = ctx.user.id if ctx.user else 0
    order, balance_after = await team_controller.query_recharge(
        out_trade_no=out_trade_no,
        user_id=user_id,
        is_super_admin=ctx.is_super_admin,
    )
    return ResponseSchema(
        data=RechargeOrderDetailOut(
            id=order.id,
            out_trade_no=order.out_trade_no,
            team_id=order.team_id,
            amount=order.amount,
            status=order.status,
            payment_method=order.payment_method,
            code_url=order.code_url,
            created_at=order.created_at,
            updated_at=order.updated_at,
            expires_at=order.expires_at,
            transaction_id=order.transaction_id,
            paid_at=order.paid_at,
            balance_after=balance_after,
        )
    )


@router.post(
    "/balance/recharge/{out_trade_no}/mock-pay",
    summary="模拟支付成功（仅在开发/测试 WECHAT_PAY_MOCK 开启时可用）",
    response_model=ResponseSchema[RechargeOrderDetailOut],
)
async def mock_pay_recharge_order(
    out_trade_no: str,
    ctx: AuthContext = Depends(get_auth_context),
):
    if not settings.WECHAT_PAY_MOCK or settings.AUTH_PROVIDER == "qiling":
        raise HTTPException(404, localized_message("充值订单不存在"))

    user_id = ctx.user.id if ctx.user else 0
    order, balance_after = await team_controller.mock_pay_recharge(
        out_trade_no=out_trade_no,
        user_id=user_id,
        is_super_admin=ctx.is_super_admin,
    )
    return ResponseSchema(
        data=RechargeOrderDetailOut(
            id=order.id,
            out_trade_no=order.out_trade_no,
            team_id=order.team_id,
            amount=order.amount,
            status=order.status,
            payment_method=order.payment_method,
            code_url=order.code_url,
            created_at=order.created_at,
            updated_at=order.updated_at,
            expires_at=order.expires_at,
            transaction_id=order.transaction_id,
            paid_at=order.paid_at,
            balance_after=balance_after,
        )
    )


@router.post(
    "/balance/recharge/wechat/notify",
    summary="微信支付异步结果通知回调",
)
async def wechat_pay_recharge_notify(request: Request):
    body = await request.body()
    return await team_controller.handle_wechat_notify(body, headers=request.headers)


@router.get(
    "/orders",
    summary="查询充值订单列表（超管查看全部用户充值，普通用户查看本人充值）",
    response_model=ResponseSchema[PaginationResponse[RechargeOrderAdminOut]],
)
async def list_recharge_orders(
    background_tasks: BackgroundTasks,
    status: str | None = Query(None, description="订单状态筛选：pending/paid/expired/closed/failed"),
    search: str | None = Query(None, description="搜索关键词：订单号/微信流水号/团队/用户/备注"),
    params=Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.user:
        raise HTTPException(401, localized_message("需要登录"))

    # 超级管理员触发后台轻量清理任务：过期待支付订单置为 expired，超过 7 天的历史失效订单彻底删除
    if ctx.is_super_admin:
        background_tasks.add_task(team_controller.cleanup_recharge_orders)

    data = await team_controller.list_orders(
        user_id=ctx.user.id,
        is_super_admin=ctx.is_super_admin,
        status=status,
        search=search,
        page=params.page,
        page_size=params.page_size,
    )
    return ResponseSchema(data=data)


@router.post(
    "/orders/{out_trade_no}/refund",
    summary="超级管理员退款（微信原路退回并扣回团队充值金额，团队余额不足时拒绝退款）",
    response_model=ResponseSchema[RechargeOrderAdminOut],
)
async def refund_recharge_order(
    out_trade_no: str,
    payload: RefundOrderIn = RefundOrderIn(),
    ctx: AuthContext = _SUPER,
):
    operator_id = ctx.user.id if ctx.user else None
    order = await team_controller.refund_recharge(
        out_trade_no=out_trade_no,
        operator_user_id=operator_id,
        reason=payload.reason,
    )
    user = await User.get_or_none(id=order.user_id)
    team = await Team.get_or_none(id=order.team_id)
    return ResponseSchema(
        data=RechargeOrderAdminOut(
            id=order.id,
            out_trade_no=order.out_trade_no,
            team_id=order.team_id,
            team_name=team.name if team else "",
            user_id=order.user_id,
            username=user.username if user else "",
            nickname=user.nickname if user else "",
            amount=order.amount,
            status=order.status,
            payment_method=order.payment_method,
            code_url=order.code_url,
            transaction_id=order.transaction_id,
            paid_at=order.paid_at,
            expires_at=order.expires_at,
            note=order.note,
            refund_id=order.refund_id,
            refunded_at=order.refunded_at,
            refund_reason=order.refund_reason,
            created_at=order.created_at,
            updated_at=order.updated_at,
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
        }
    )


# ---------------------------------------------------------------- 成员


@router.get(
    "/members",
    summary="团队成员列表（分页，含累计消耗、限额与团队人数上限）",
    response_model=ResponseSchema[MemberPaginationResponse],
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
            _team_id_or_own(ctx, team_id), user_id, payload.cost_limit, _operator_id(ctx)
        )
    )


@router.post("/members/{user_id}/reset-password", dependencies=[Depends(password_provider)])
async def reset_member_password(user_id: int, payload: MemberResetPasswordIn,
                                ctx: AuthContext = _ADMIN, team_id: int | None = Query(None, ge=1)):
    await team_controller.reset_member_password(_team_id_or_own(ctx, team_id), user_id,
                                                payload.new_password, _operator_id(ctx))
    return ResponseSchema(data=None)


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
            "created_at": team.created_at,
            "updated_at": team.updated_at,
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
