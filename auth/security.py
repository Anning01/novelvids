"""密码哈希与会话令牌工具（仅用标准库，不新增依赖）。"""

import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """生成 pbkdf2_sha256 密码哈希，格式：算法$迭代次数$盐hex$摘要hex。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码与存储哈希是否匹配；任何解析失败都视为不匹配。"""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def new_session_token() -> str:
    """生成随机会话令牌（原始值返回给前端，库中只存哈希）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """会话令牌入库前做单向哈希。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
