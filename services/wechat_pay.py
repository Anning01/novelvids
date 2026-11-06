"""微信支付 v3 服务封装（支持 Native 扫码支付、查单与回调验签解密）。"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

from config import settings

logger = logging.getLogger(__name__)


def _sanitize_wechat_text(text: str) -> str:
    """过滤 4 字节 UTF-8 字符（Emoji 等非 BMP 字符）。

    微信支付网关底层对 4 字节 UTF-8 字符不兼容，会报 INVALID_REQUEST (非UTF8参数)。
    因此在向微信发起请求时，必须清洗掉所有码点 > 0xFFFF 的字符。
    """
    if not text:
        return ""
    return "".join(ch for ch in text if ord(ch) <= 0xFFFF).strip()


class WeChatPayError(RuntimeError):
    """微信支付异常。"""


class WeChatPayService:
    """微信支付 v3 客户端。"""

    GATEWAY = "https://api.mch.weixin.qq.com"

    def __init__(self) -> None:
        self.app_id = settings.WECHAT_PAY_APP_ID
        self.mch_id = settings.WECHAT_PAY_MCH_ID
        self.api_v3_key = settings.WECHAT_PAY_API_V3_KEY
        self.serial_no = settings.WECHAT_PAY_SERIAL_NO
        self.private_key_pem = settings.WECHAT_PAY_PRIVATE_KEY
        self.private_key_path = settings.WECHAT_PAY_PRIVATE_KEY_PATH
        self.public_key_pem = settings.WECHAT_PAY_PUBLIC_KEY
        self.public_key_path = settings.WECHAT_PAY_PUBLIC_KEY_PATH
        self.public_key_id = settings.WECHAT_PAY_PUBLIC_KEY_ID
        self.notify_url = settings.WECHAT_PAY_NOTIFY_URL
        self.is_mock = settings.WECHAT_PAY_MOCK
        self._private_key = self._load_private_key()
        self._public_key = self._load_public_key()

    def _load_public_key(self) -> Any:
        pem_bytes: bytes | None = None
        if self.public_key_pem:
            pem_bytes = self.public_key_pem.encode("utf-8")
        elif self.public_key_path:
            path = Path(self.public_key_path)
            if path.is_file():
                pem_bytes = path.read_bytes()

        if not pem_bytes:
            return None

        try:
            return load_pem_public_key(pem_bytes)
        except Exception as exc:
            logger.warning("wechat_pay_load_public_key_failed: %s", exc)
            return None

    def _load_private_key(self) -> Any:
        pem_bytes: bytes | None = None
        if self.private_key_pem:
            pem_bytes = self.private_key_pem.encode("utf-8")
        elif self.private_key_path:
            path = Path(self.private_key_path)
            if path.is_file():
                pem_bytes = path.read_bytes()

        if not pem_bytes:
            return None

        try:
            return load_pem_private_key(pem_bytes, password=None)
        except Exception as exc:
            logger.warning("wechat_pay_load_key_failed: %s", exc)
            return None

    def is_configured(self) -> bool:
        """检查必要商户参数是否完整就绪。"""
        return bool(
            self.app_id
            and self.mch_id
            and self.api_v3_key
            and self.serial_no
            and self._private_key
        )

    def missing_configs(self) -> list[str]:
        """返回尚未配置的参数列表。"""
        missing: list[str] = []
        if not self.app_id:
            missing.append("WECHAT_PAY_APP_ID")
        if not self.mch_id:
            missing.append("WECHAT_PAY_MCH_ID")
        if not self.api_v3_key:
            missing.append("WECHAT_PAY_API_V3_KEY")
        if not self.serial_no:
            missing.append("WECHAT_PAY_SERIAL_NO")
        if not self._private_key:
            missing.append("WECHAT_PAY_PRIVATE_KEY 或 WECHAT_PAY_PRIVATE_KEY_PATH")
        return missing

    def build_authorization(self, method: str, url_path: str, body: str = "") -> str:
        """生成微信支付 v3 Authorization 签名请求头。"""
        if not self._private_key:
            raise WeChatPayError("商户私钥未加载，无法生成签名")

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
        sig = self._private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature = base64.b64encode(sig).decode("utf-8")
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.mch_id}",'
            f'nonce_str="{nonce}",signature="{signature}",'
            f'timestamp="{timestamp}",serial_no="{self.serial_no}"'
        )

    async def create_native_order(
        self,
        out_trade_no: str,
        amount_yuan: Decimal,
        description: str,
        attach: str = "",
    ) -> dict[str, Any]:
        """发起微信 Native 扫码下单，返回 code_url。"""
        if self.is_mock:
            logger.info("wechat_pay_mock_order_created out_trade_no=%s amount=%s", out_trade_no, amount_yuan)
            return {
                "code_url": f"weixin://wxpay/bizpayurl?pr=mock_{out_trade_no}",
                "mock": True,
            }

        if not self.is_configured():
            missing = ", ".join(self.missing_configs())
            raise WeChatPayError(f"微信支付商户配置未就绪，缺少配置: {missing}")

        total_cents = int(amount_yuan * 100)
        if total_cents <= 0:
            raise WeChatPayError("充值金额必须大于零")

        clean_desc = _sanitize_wechat_text(description)[:127] or "团队充值"
        clean_attach = _sanitize_wechat_text(attach)[:127]

        path = "/v3/pay/transactions/native"
        url = f"{self.GATEWAY}{path}"
        payload: dict[str, Any] = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": clean_desc,
            "out_trade_no": out_trade_no,
            "notify_url": self.notify_url or f"https://example.com{path}",
            "amount": {
                "total": total_cents,
                "currency": "CNY",
            },
        }
        if clean_attach:
            payload["attach"] = clean_attach

        body = json.dumps(payload, ensure_ascii=False)
        auth_header = self.build_authorization("POST", path, body)
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "novelvids-studio/1.0",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(url, headers=headers, content=body)
            except httpx.HTTPError as exc:
                logger.error("wechat_pay_request_error: %s", exc)
                raise WeChatPayError("网络请求微信支付网关失败") from exc

        if resp.status_code >= 400:
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            msg = err_data.get("message") or err_data.get("detail") or resp.text[:200]
            code = err_data.get("code") or f"HTTP_{resp.status_code}"
            logger.error("wechat_pay_native_failed status=%d code=%s msg=%s", resp.status_code, code, msg)
            raise WeChatPayError(f"微信支付下单失败: {msg}（{code}）")

        return resp.json()

    def validate_payment(self, payload: dict[str, Any], out_trade_no: str, amount: Decimal) -> None:
        received = payload.get("amount")
        if (not isinstance(received, dict) or type(received.get("total")) is not int
                or received["total"] != int(amount * 100) or received.get("currency") != "CNY"
                or not self.mch_id or payload.get("mchid") != self.mch_id
                or not self.app_id or payload.get("appid") != self.app_id
                or payload.get("out_trade_no") != out_trade_no or not payload.get("transaction_id")):
            raise WeChatPayError("支付金额或订单身份不匹配")

    async def query_order(self, out_trade_no: str) -> dict[str, Any]:
        """查询订单状态。"""
        if self.is_mock or not self.is_configured():
            return {"trade_state": "NOTPAY", "out_trade_no": out_trade_no}

        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={self.mch_id}"
        url = f"{self.GATEWAY}{path}"
        auth_header = self.build_authorization("GET", path, "")
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "User-Agent": "novelvids-studio/1.0",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("wechat_pay_query_error out_trade_no=%s: %s", out_trade_no, exc)
                return {"trade_state": "NOTPAY", "out_trade_no": out_trade_no}

        if resp.status_code == 200:
            return resp.json()
        return {"trade_state": "NOTPAY", "out_trade_no": out_trade_no}

    async def create_refund(
        self,
        out_trade_no: str,
        out_refund_no: str,
        amount_yuan: Decimal,
        total_yuan: Decimal,
        reason: str = "",
    ) -> dict[str, Any]:
        """发起微信支付退款申请（POST /v3/refund/domestic/refunds）。"""
        if self.is_mock:
            logger.info(
                "wechat_pay_mock_refund out_trade_no=%s out_refund_no=%s amount=%s",
                out_trade_no,
                out_refund_no,
                amount_yuan,
            )
            return {
                "refund_id": f"MOCK_REFUND_{uuid.uuid4().hex[:12]}",
                "out_refund_no": out_refund_no,
                "out_trade_no": out_trade_no,
                "status": "SUCCESS",
                "mock": True,
            }

        if not self.is_configured():
            missing = ", ".join(self.missing_configs())
            raise WeChatPayError(f"微信支付商户配置未就绪，缺少配置: {missing}")

        refund_cents = int(amount_yuan * 100)
        total_cents = int(total_yuan * 100)
        if refund_cents <= 0 or total_cents <= 0:
            raise WeChatPayError("退款金额和订单总金额必须大于零")

        clean_reason = _sanitize_wechat_text(reason)[:80] or "管理员退款"

        path = "/v3/refund/domestic/refunds"
        url = f"{self.GATEWAY}{path}"
        payload: dict[str, Any] = {
            "out_trade_no": out_trade_no,
            "out_refund_no": out_refund_no,
            "reason": clean_reason,
            "amount": {
                "refund": refund_cents,
                "total": total_cents,
                "currency": "CNY",
            },
        }

        body = json.dumps(payload, ensure_ascii=False)
        auth_header = self.build_authorization("POST", path, body)
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "novelvids-studio/1.0",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(url, headers=headers, content=body)
            except httpx.HTTPError as exc:
                logger.error("wechat_pay_refund_request_error: %s", exc)
                raise WeChatPayError("网络请求微信退款接口失败") from exc

        if resp.status_code >= 400:
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            msg = err_data.get("message") or err_data.get("detail") or resp.text[:200]
            code = err_data.get("code") or f"HTTP_{resp.status_code}"
            logger.error("wechat_pay_refund_failed status=%d code=%s msg=%s", resp.status_code, code, msg)
            raise WeChatPayError(f"微信支付退款失败: {msg}（{code}）")

        return resp.json()

    async def query_refund(self, out_refund_no: str) -> dict[str, Any]:
        if self.is_mock:
            return {"status": "SUCCESS", "refund_id": f"MOCK_{out_refund_no}"}
        if not self.is_configured():
            raise WeChatPayError("微信支付商户配置未就绪")
        path = f"/v3/refund/domestic/refunds/{out_refund_no}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.GATEWAY + path, headers={
                    "Authorization": self.build_authorization("GET", path), "Accept": "application/json"})
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeChatPayError("查询退款状态失败") from exc

    def decrypt_callback(self, ciphertext: str, nonce: str, associated_data: str = "") -> dict[str, Any]:
        """解密微信支付回调的 AES-256-GCM 密文。"""
        if not self.api_v3_key:
            raise WeChatPayError("WECHAT_PAY_API_V3_KEY 未配置，无法解密回调")

        key_bytes = self.api_v3_key.encode("utf-8")
        if len(key_bytes) != 32:
            raise WeChatPayError("WECHAT_PAY_API_V3_KEY 必须为 32 字节字符")

        nonce_bytes = nonce.encode("utf-8")
        aad_bytes = (associated_data or "").encode("utf-8")
        raw_ciphertext = base64.b64decode(ciphertext)

        aesgcm = AESGCM(key_bytes)
        try:
            decrypted = aesgcm.decrypt(nonce_bytes, raw_ciphertext, aad_bytes)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as exc:
            logger.error("wechat_pay_decrypt_failed: %s", exc)
            raise WeChatPayError("微信支付回调密文解密失败") from exc

    def verify_signature(
        self,
        timestamp: str,
        nonce: str,
        body: str,
        signature: str,
        serial_no: str = "",
    ) -> bool:
        """使用微信支付平台公钥验签回调请求。

        缺少平台公钥或公钥标识不匹配时拒绝，避免绕过验签。
        """
        # 防重放攻击：校验时间戳与服务器时间偏差（微信规范要求不超过 5 分钟）
        try:
            if abs(int(time.time()) - int(timestamp)) > 300:
                logger.warning("wechat_pay_signature_timestamp_expired: %s", timestamp)
                return False
        except (ValueError, TypeError):
            logger.warning("wechat_pay_signature_invalid_timestamp: %s", timestamp)
            return False

        if self._public_key is None:
            return False

        if self.public_key_id and self.public_key_id != serial_no:
            logger.warning(
                "wechat_pay_serial_mismatch: configured=%s, received=%s",
                self.public_key_id,
                serial_no,
            )
            return False

        message = f"{timestamp}\n{nonce}\n{body}\n"
        try:
            sig_bytes = base64.b64decode(signature)
            self._public_key.verify(
                sig_bytes,
                message.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except (InvalidSignature, Exception) as exc:
            logger.error("wechat_pay_verify_signature_failed: %s", exc)
            return False


wechat_pay_service = WeChatPayService()
