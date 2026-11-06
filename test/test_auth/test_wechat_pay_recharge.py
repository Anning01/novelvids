"""微信支付 v3 团队充值测试。

覆盖：
1. WeChatPayService 单元测试（配置检查、RSA 签名、AES-256-GCM 回调解密）；
2. 充值下单接口（POST /api/team/balance/recharge）；
3. 充值查单接口（GET /api/team/balance/recharge/{out_trade_no}）；
4. 微信支付结果通知（POST /api/payment/wechat/notify）；
5. 幂等性：同一订单多次回调或多次查询仅入账一次；
6. 权限保护：非团队成员禁止为该团队下单或查单。
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from httpx import ASGITransport, AsyncClient
from tortoise.timezone import now as tz_now

from auth.models import BalanceTransaction, RechargeOrder, Team, TeamMember, User
from config import settings
from main import app
from services.wechat_pay import WeChatPayError, WeChatPayService
from test.test_auth import issue_test_session

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时余额与充值功能未启用"
)


def _gen_rsa_key_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv, priv_pem, pub_pem


@pytest.fixture
def mock_wechat_keys(monkeypatch):
    mch_priv, mch_pem, _ = _gen_rsa_key_pair()
    plat_priv, _, plat_pub_pem = _gen_rsa_key_pair()

    monkeypatch.setattr(settings, "WECHAT_PAY_APP_ID", "wx1234567890abcdef")
    monkeypatch.setattr(settings, "WECHAT_PAY_MCH_ID", "1900000109")
    monkeypatch.setattr(settings, "WECHAT_PAY_API_V3_KEY", "12345678901234567890123456789012")
    monkeypatch.setattr(settings, "WECHAT_PAY_SERIAL_NO", "78901234567890ABCDEF")
    monkeypatch.setattr(settings, "WECHAT_PAY_PRIVATE_KEY", mch_pem)
    monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY", plat_pub_pem)
    monkeypatch.setattr(settings, "WECHAT_PAY_PUBLIC_KEY_ID", "PUB_KEY_ID_TEST_001")
    monkeypatch.setattr(settings, "WECHAT_PAY_MOCK", True)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "password")
    from services.wechat_pay import wechat_pay_service

    wechat_pay_service.app_id = settings.WECHAT_PAY_APP_ID
    wechat_pay_service.mch_id = settings.WECHAT_PAY_MCH_ID
    wechat_pay_service.api_v3_key = settings.WECHAT_PAY_API_V3_KEY
    wechat_pay_service.serial_no = settings.WECHAT_PAY_SERIAL_NO
    wechat_pay_service.private_key_pem = mch_pem
    wechat_pay_service._private_key = wechat_pay_service._load_private_key()
    wechat_pay_service.public_key_pem = plat_pub_pem
    wechat_pay_service.public_key_id = "PUB_KEY_ID_TEST_001"
    wechat_pay_service._public_key = wechat_pay_service._load_public_key()
    wechat_pay_service.is_mock = True
    # 将微信平台私钥挂载到 service 方便测试构造合法的微信签名
    wechat_pay_service._plat_priv_for_test = plat_priv
    return wechat_pay_service


@pytest.mark.asyncio
async def test_wechat_pay_service_authorization_signature(mock_wechat_keys):
    service = mock_wechat_keys
    assert service.is_configured() is True
    assert len(service.missing_configs()) == 0

    header = service.build_authorization("POST", "/v3/pay/transactions/native", "{}")
    assert header.startswith("WECHATPAY2-SHA256-RSA2048 ")
    assert 'mchid="1900000109"' in header
    assert 'serial_no="78901234567890ABCDEF"' in header


@pytest.mark.asyncio
async def test_wechat_pay_service_decrypt_callback(mock_wechat_keys):
    service = mock_wechat_keys
    v3_key = service.api_v3_key.encode("utf-8")
    aesgcm = AESGCM(v3_key)
    nonce = b"123456789012"
    aad = b"transaction"
    plain_data = {
        "out_trade_no": "REC_CALLBACK_TEST",
        "trade_state": "SUCCESS",
        "transaction_id": "WX_TXN_9999",
    }
    ciphertext_raw = aesgcm.encrypt(nonce, json.dumps(plain_data).encode("utf-8"), aad)
    ciphertext_b64 = base64.b64encode(ciphertext_raw).decode("utf-8")

    decrypted = service.decrypt_callback(
        ciphertext=ciphertext_b64,
        nonce="123456789012",
        associated_data="transaction",
    )
    assert decrypted["out_trade_no"] == "REC_CALLBACK_TEST"
    assert decrypted["trade_state"] == "SUCCESS"


@pytest.mark.asyncio
async def test_member_can_create_recharge_order_and_poll_status(mock_wechat_keys):
    team = await Team.create(name="充值测试队", balance=Decimal("100.000000"))
    member = await User.create(username="recharge_member", nickname="充值成员")
    await TeamMember.create(team=team, user=member, role="creator", status=1)
    token = await issue_test_session("recharge_member")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 创建充值订单
        resp = await client.post(
            "/api/team/balance/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"team_id": team.id, "amount": 50, "note": "微信充值测试"},
        )
        assert resp.status_code == 200
        order_data = resp.json()["data"]
        out_trade_no = order_data["out_trade_no"]
        assert order_data["team_id"] == team.id
        assert Decimal(order_data["amount"]) == Decimal("50.00")
        assert order_data["status"] == "pending"
        assert order_data["code_url"].startswith("weixin://")

        # 2. 查询待支付状态
        query_resp = await client.get(
            f"/api/team/balance/recharge/{out_trade_no}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert query_resp.status_code == 200
        assert query_resp.json()["data"]["status"] == "pending"

        # 3. 模拟支付成功（Mock 模式）
        mock_pay_resp = await client.post(
            f"/api/team/balance/recharge/{out_trade_no}/mock-pay",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert mock_pay_resp.status_code == 200
        paid_data = mock_pay_resp.json()["data"]
        assert paid_data["status"] == "paid"
        assert paid_data["transaction_id"] is not None
        assert Decimal(paid_data["balance_after"]) == Decimal("150.000000")

        # 4. 再次查询，状态保持 paid
        query_resp2 = await client.get(
            f"/api/team/balance/recharge/{out_trade_no}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert query_resp2.status_code == 200
        assert query_resp2.json()["data"]["status"] == "paid"

        # 5. 验证流水入账
        transactions = await BalanceTransaction.filter(team=team, type="topup").all()
        assert len(transactions) == 1
        assert transactions[0].change_amount == Decimal("50.000000")
        assert transactions[0].balance_after == Decimal("150.000000")


@pytest.mark.asyncio
async def test_wechat_pay_webhook_notify_credits_balance(mock_wechat_keys):
    team = await Team.create(name="回调入账队", balance=Decimal("20.000000"))
    member = await User.create(username="webhook_member", nickname="回调成员")
    await TeamMember.create(team=team, user=member, role="admin", status=1)

    order = await RechargeOrder.create(
        out_trade_no="REC_WEBHOOK_001",
        team=team,
        user_id=member.id,
        amount=Decimal("200.00"),
        status="pending",
        code_url="weixin://wxpay/bizpayurl?pr=mock_001",
    )

    # 构造加密的回调数据
    service = mock_wechat_keys
    v3_key = service.api_v3_key.encode("utf-8")
    aesgcm = AESGCM(v3_key)
    nonce = b"nonce1234567"
    aad = b"notify_aad"
    trade_data = {
        "out_trade_no": order.out_trade_no,
        "trade_state": "SUCCESS",
        "transaction_id": "WX_TXN_888888",
        "mchid": service.mch_id,
        "appid": service.app_id,
        "amount": {"total": 20000, "currency": "CNY"},
    }
    cipher = aesgcm.encrypt(nonce, json.dumps(trade_data).encode("utf-8"), aad)
    webhook_body = {
        "id": "EVENT_001",
        "create_time": "2026-11-06T12:00:00+08:00",
        "resource_type": "encrypt-resource",
        "event_type": "TRANSACTION.SUCCESS",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(cipher).decode("utf-8"),
            "associated_data": "notify_aad",
            "nonce": "nonce1234567",
        },
    }

    raw_body = json.dumps(webhook_body, ensure_ascii=False)
    import time
    timestamp = str(int(time.time()))
    nonce_str = "nonce_random_abc"
    message_to_sign = f"{timestamp}\n{nonce_str}\n{raw_body}\n"
    sig = service._plat_priv_for_test.sign(
        message_to_sign.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(sig).decode("utf-8")
    valid_headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce_str,
        "Wechatpay-Signature": sig_b64,
        "Wechatpay-Serial": "PUB_KEY_ID_TEST_001",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 签名错误时拒绝
        bad_headers = {**valid_headers, "Wechatpay-Signature": "invalid_signature"}
        bad_resp = await client.post(
            "/api/payment/wechat/notify",
            content=raw_body,
            headers=bad_headers,
        )
        assert bad_resp.json()["code"] == "FAIL"

        # 2. 正确签名时正常入账
        resp = await client.post(
            "/api/payment/wechat/notify",
            content=raw_body,
            headers=valid_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == "SUCCESS"

        # 检查订单状态与团队余额
        await order.refresh_from_db()
        assert order.status == "paid"
        assert order.transaction_id == "WX_TXN_888888"

        await team.refresh_from_db()
        assert team.balance == Decimal("220.000000")

        # 幂等性测试：再次发送同一回调，余额不能重复增加
        resp2 = await client.post(
            "/api/payment/wechat/notify",
            content=raw_body,
            headers=valid_headers,
        )
        assert resp2.status_code == 200
        await team.refresh_from_db()
        assert team.balance == Decimal("220.000000")


@pytest.mark.asyncio
async def test_non_member_cannot_recharge_other_team(mock_wechat_keys):
    team_a = await Team.create(name="队伍A")
    team_b = await Team.create(name="队伍B")
    user_a = await User.create(username="user_team_a")
    await TeamMember.create(team=team_a, user=user_a, role="creator", status=1)
    token_a = await issue_test_session("user_team_a")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/team/balance/recharge",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"team_id": team_b.id, "amount": 100},
        )
        assert resp.json()["code"] == 403


@pytest.mark.asyncio
async def test_qiling_edition_blocks_mock_pay(mock_wechat_keys, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "qiling")
    team = await Team.create(name="器灵版本安全队")
    user = await User.create(username="qiling_user")
    await TeamMember.create(team=team, user=user, role="admin", status=1)
    token = await issue_test_session("qiling_user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 即使传合法的订单号，在器灵部署版本中 mock-pay 必须返回 404
        resp = await client.post(
            "/api/team/balance/recharge/REC_ANY_ORDER/mock-pay",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["code"] == 404


@pytest.mark.asyncio
async def test_tampered_amount_in_notify_rejected(mock_wechat_keys):
    team = await Team.create(name="防金额篡改队", balance=Decimal("10.000000"))
    user = await User.create(username="amount_victim")
    await TeamMember.create(team=team, user=user, role="admin", status=1)

    order = await RechargeOrder.create(
        out_trade_no="REC_TAMPER_001",
        team=team,
        user_id=user.id,
        amount=Decimal("1000.00"),  # 订单要充 1000 元
        status="pending",
    )

    service = mock_wechat_keys
    v3_key = service.api_v3_key.encode("utf-8")
    aesgcm = AESGCM(v3_key)
    nonce = b"nonce1234567"
    aad = b"notify_aad"
    # 攻击者尝试在微信端仅支付 1 分钱（1分 != 100000分）
    trade_data = {
        "out_trade_no": order.out_trade_no,
        "trade_state": "SUCCESS",
        "transaction_id": "WX_TXN_TAMPER",
        "mchid": service.mch_id,
        "appid": service.app_id,
        "amount": {"total": 1, "currency": "CNY"},
    }
    cipher = aesgcm.encrypt(nonce, json.dumps(trade_data).encode("utf-8"), aad)
    webhook_body = {
        "id": "EVENT_TAMPER",
        "create_time": "2026-11-06T12:00:00+08:00",
        "resource_type": "encrypt-resource",
        "event_type": "TRANSACTION.SUCCESS",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(cipher).decode("utf-8"),
            "associated_data": "notify_aad",
            "nonce": "nonce1234567",
        },
    }
    raw_body = json.dumps(webhook_body, ensure_ascii=False)
    import time
    timestamp = str(int(time.time()))
    nonce_str = "nonce_random_abc"
    message_to_sign = f"{timestamp}\n{nonce_str}\n{raw_body}\n"
    sig = service._plat_priv_for_test.sign(
        message_to_sign.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(sig).decode("utf-8")
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce_str,
        "Wechatpay-Signature": sig_b64,
        "Wechatpay-Serial": "PUB_KEY_ID_TEST_001",
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/payment/wechat/notify",
            content=raw_body,
            headers=headers,
        )
        assert resp.json()["code"] == "FAIL"
        assert "金额不匹配" in resp.json()["message"]

        # 验证余额未增加，订单未被入账
        await order.refresh_from_db()
        assert order.status == "pending"
        await team.refresh_from_db()
        assert team.balance == Decimal("10.000000")


@pytest.mark.asyncio
async def test_emoji_in_team_name_is_sanitized_for_wechat(mock_wechat_keys):
    """验证包含 4 字节 Emoji（如 📖）的团队名称在提交给微信下单时已被清洗，避免微信报非 UTF-8 错误。"""
    team = await Team.create(name="📖Yue的团队", balance=Decimal("0.000000"))
    user = await User.create(username="yue_user")
    await TeamMember.create(team=team, user=user, role="admin", status=1)
    token = await issue_test_session("yue_user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/team/balance/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"team_id": team.id, "amount": 50},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["team_id"] == team.id
        assert data["status"] == "pending"
        assert data["code_url"].startswith("weixin://")


@pytest.mark.asyncio
async def test_recharge_order_expires_in_15_minutes_and_marks_expired_on_query(mock_wechat_keys, monkeypatch):
    """测试充值订单过期时间为 15 分钟，且超过 15 分钟后查单自动标记为 expired。"""
    team = await Team.create(name="超时测试队", balance=Decimal("0.000000"))
    user = await User.create(username="timeout_user")
    await TeamMember.create(team=team, user=user, role="admin", status=1)
    token = await issue_test_session("timeout_user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/team/balance/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"team_id": team.id, "amount": 20},
        )
        assert resp.status_code == 200
        order_data = resp.json()["data"]
        out_trade_no = order_data["out_trade_no"]

        order = await RechargeOrder.get(out_trade_no=out_trade_no)
        # 验证默认过期时间约为 15 分钟
        time_diff = (order.expires_at - order.created_at).total_seconds()
        assert 800 <= time_diff <= 1000

        # 将订单过期时间调整到过去
        order.expires_at = tz_now() - timedelta(minutes=5)
        await order.save(update_fields=["expires_at"])

        # 模拟微信端仍返回 NOTPAY（未支付）
        async def mock_notpay(out_no):
            return {"trade_state": "NOTPAY"}
        monkeypatch.setattr(mock_wechat_keys, "query_order", mock_notpay)

        query_resp = await client.get(
            f"/api/team/balance/recharge/{out_trade_no}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert query_resp.status_code == 200
        assert query_resp.json()["data"]["status"] == "expired"

        await order.refresh_from_db()
        assert order.status == "expired"


@pytest.mark.asyncio
async def test_active_query_recharge_auto_credits_on_wechat_success(mock_wechat_keys, monkeypatch):
    """验证主动查询微信时如果返回 SUCCESS，无需等待异步回调即可自动入账。"""
    team = await Team.create(name="主动查单队", balance=Decimal("10.000000"))
    user = await User.create(username="active_query_user")
    await TeamMember.create(team=team, user=user, role="admin", status=1)
    token = await issue_test_session("active_query_user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/team/balance/recharge",
            headers={"Authorization": f"Bearer {token}"},
            json={"team_id": team.id, "amount": 100},
        )
        assert resp.status_code == 200
        out_trade_no = resp.json()["data"]["out_trade_no"]

        # 模拟微信查询返回 SUCCESS
        async def mock_success(out_no):
            return {"trade_state": "SUCCESS", "transaction_id": "WX_ACTIVE_123456", "out_trade_no": out_no,
                    "mchid": mock_wechat_keys.mch_id, "appid": mock_wechat_keys.app_id,
                    "amount": {"total": 10000, "currency": "CNY"}}
        monkeypatch.setattr(mock_wechat_keys, "query_order", mock_success)

        # 客户端轮询查单
        query_resp = await client.get(
            f"/api/team/balance/recharge/{out_trade_no}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert query_resp.status_code == 200
        data = query_resp.json()["data"]
        assert data["status"] == "paid"
        assert data["transaction_id"] == "WX_ACTIVE_123456"
        assert Decimal(data["balance_after"]) == Decimal("110.00")

        await team.refresh_from_db()
        assert team.balance == Decimal("110.000000")


@pytest.mark.asyncio
async def test_cleanup_recharge_orders_logic():
    """测试后台清理：待支付订单超时置为 expired，超过 7 天失效订单彻底删除，已支付订单安全保留。"""
    from controllers.team import team_controller

    team = await Team.create(name="清理测试队", balance=Decimal("0.000000"))
    now = tz_now()

    # 1. 待支付且已超时的订单
    pending_overdue = await RechargeOrder.create(
        out_trade_no="REC_CLEANUP_PENDING_01",
        team=team,
        user_id=1,
        amount=Decimal("10"),
        status="pending",
        expires_at=now - timedelta(minutes=1),
    )
    # 2. 超过 7 天的历史失效订单
    old_expired = await RechargeOrder.create(
        out_trade_no="REC_CLEANUP_OLD_EXPIRED",
        team=team,
        user_id=1,
        amount=Decimal("20"),
        status="expired",
        created_at=now - timedelta(days=8),
    )
    # 3. 超过 7 天但已支付成功的订单（不得删除！）
    old_paid = await RechargeOrder.create(
        out_trade_no="REC_CLEANUP_OLD_PAID",
        team=team,
        user_id=1,
        amount=Decimal("30"),
        status="paid",
        created_at=now - timedelta(days=8),
        paid_at=now - timedelta(days=8),
    )

    # 触发清理
    await team_controller.cleanup_recharge_orders()

    await pending_overdue.refresh_from_db()
    assert pending_overdue.status == "expired"

    assert await RechargeOrder.filter(id=old_expired.id).first() is None
    assert await RechargeOrder.filter(id=old_paid.id).first() is not None


@pytest.mark.asyncio
async def test_list_recharge_orders_api_scoping_and_filters(mock_wechat_keys):
    """测试充值订单管理接口：普通用户仅查看个人充值，超级管理员查看全部，支持状态与关键词筛选。"""
    team_a = await Team.create(name="团队Alpha", balance=Decimal("0.000000"))
    team_b = await Team.create(name="团队Beta", balance=Decimal("0.000000"))

    user_a = await User.create(username="order_user_a", nickname="小甲")
    user_b = await User.create(username="order_user_b", nickname="小乙")
    super_user = await User.create(username="order_super_admin", is_super_admin=True)

    await TeamMember.create(team=team_a, user=user_a, role="admin", status=1)
    await TeamMember.create(team=team_b, user=user_b, role="admin", status=1)

    order_a = await RechargeOrder.create(
        out_trade_no="REC_USER_A_001",
        team=team_a,
        user_id=user_a.id,
        amount=Decimal("50.00"),
        status="paid",
        note="甲的充值",
    )
    order_b = await RechargeOrder.create(
        out_trade_no="REC_USER_B_001",
        team=team_b,
        user_id=user_b.id,
        amount=Decimal("100.00"),
        status="pending",
        note="乙的充值",
    )

    token_a = await issue_test_session("order_user_a")
    token_super = await issue_test_session("order_super_admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 普通用户 A 查询订单
        resp_a = await client.get(
            "/api/team/orders",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200
        data_a = resp_a.json()["data"]
        items_a = data_a["items"]
        assert len(items_a) == 1
        assert items_a[0]["out_trade_no"] == "REC_USER_A_001"
        assert items_a[0]["team_name"] == "团队Alpha"
        assert data_a["pagination"]["total"] == 1
        assert data_a["pagination"]["page"] == 1

        # 超级管理员查询全部订单
        resp_super = await client.get(
            "/api/team/orders",
            headers={"Authorization": f"Bearer {token_super}"},
        )
        assert resp_super.status_code == 200
        items_super = resp_super.json()["data"]["items"]
        out_nos = [item["out_trade_no"] for item in items_super]
        assert "REC_USER_A_001" in out_nos
        assert "REC_USER_B_001" in out_nos

        # 超管筛选状态：仅待支付
        resp_filter = await client.get(
            "/api/team/orders?status=pending",
            headers={"Authorization": f"Bearer {token_super}"},
        )
        filter_items = resp_filter.json()["data"]["items"]
        assert all(it["status"] == "pending" for it in filter_items)
        assert "REC_USER_B_001" in [it["out_trade_no"] for it in filter_items]

        # 关键词搜索：按团队名称
        resp_search = await client.get(
            "/api/team/orders?search=Alpha",
            headers={"Authorization": f"Bearer {token_super}"},
        )
        search_items = resp_search.json()["data"]["items"]
        assert any(it["out_trade_no"] == "REC_USER_A_001" for it in search_items)


@pytest.mark.asyncio
async def test_super_admin_refund_paid_order_and_deducts_balance(mock_wechat_keys):
    """测试超级管理员对已支付充值订单退款：调用微信退款并扣回团队余额。"""
    team = await Team.create(name="退款测试队", balance=Decimal("150.000000"))
    user = await User.create(username="refund_user_01")
    await User.create(username="refund_super_admin", is_super_admin=True)

    order = await RechargeOrder.create(
        out_trade_no="REC_REFUND_SUCCESS_01",
        team=team,
        user_id=user.id,
        amount=Decimal("50.00"),
        status="paid",
        paid_at=tz_now(),
        transaction_id="WX_TXN_REFUND_01",
    )

    token_super = await issue_test_session("refund_super_admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/team/orders/{order.out_trade_no}/refund",
            headers={"Authorization": f"Bearer {token_super}"},
            json={"reason": "用户协商退款"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "refunded"
        assert data["refund_id"] is not None
        assert data["refund_reason"] == "用户协商退款"

        # 验证团队余额扣减 50 元：150 -> 100
        await team.refresh_from_db()
        assert team.balance == Decimal("100.000000")

        # 验证退款流水记录
        tx = await BalanceTransaction.filter(team=team, type="refund").first()
        assert tx is not None
        assert tx.change_amount == Decimal("-50.000000")
        assert tx.balance_after == Decimal("100.000000")

        # 验证不可重复退款
        dup_resp = await client.post(
            f"/api/team/orders/{order.out_trade_no}/refund",
            headers={"Authorization": f"Bearer {token_super}"},
        )
        assert dup_resp.json()["code"] == 400
        assert "不可重复退款" in dup_resp.json()["message"] or "已完成退款" in dup_resp.json()["message"]


@pytest.mark.asyncio
async def test_refund_rejected_when_team_balance_insufficient(mock_wechat_keys):
    """测试若团队余额不足以扣回充值金额，则拒绝退款，不发起微信退款且余额不受影响。"""
    # 充值了 100 元，但中途消费了 80 元，当前余额仅剩 20 元
    team = await Team.create(name="余额不足队", balance=Decimal("20.000000"))
    user = await User.create(username="broke_user")
    await User.create(username="broke_super_admin", is_super_admin=True)

    order = await RechargeOrder.create(
        out_trade_no="REC_REFUND_FAIL_01",
        team=team,
        user_id=user.id,
        amount=Decimal("100.00"),
        status="paid",
        paid_at=tz_now(),
        transaction_id="WX_TXN_BROKE_01",
    )

    token_super = await issue_test_session("broke_super_admin")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/team/orders/{order.out_trade_no}/refund",
            headers={"Authorization": f"Bearer {token_super}"},
            json={"reason": "申请退款"},
        )
        assert resp.json()["code"] == 400
        assert "余额不足" in resp.json()["message"]
        assert "不支持退款" in resp.json()["message"]

        # 验证团队余额未被扣减，订单状态保持 paid
        await team.refresh_from_db()
        assert team.balance == Decimal("20.000000")

        await order.refresh_from_db()
        assert order.status == "paid"
        assert order.refund_id is None


@pytest.mark.asyncio
async def test_non_super_admin_cannot_refund_order(mock_wechat_keys):
    """测试普通用户或团队管理员无权调用退款接口。"""
    team = await Team.create(name="权限测试队", balance=Decimal("100.000000"))
    user = await User.create(username="normal_user")
    await TeamMember.create(team=team, user=user, role="admin", status=1)

    order = await RechargeOrder.create(
        out_trade_no="REC_AUTH_FAIL_01",
        team=team,
        user_id=user.id,
        amount=Decimal("50.00"),
        status="paid",
    )

    token_normal = await issue_test_session("normal_user")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/team/orders/{order.out_trade_no}/refund",
            headers={"Authorization": f"Bearer {token_normal}"},
        )
        assert resp.json()["code"] == 403
