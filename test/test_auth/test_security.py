"""密码哈希与会话令牌工具测试。"""

import pytest

from auth.security import (
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)


@pytest.mark.asyncio
async def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong password", stored)


@pytest.mark.asyncio
async def test_password_hash_is_salted():
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


@pytest.mark.asyncio
async def test_verify_password_rejects_malformed_hash():
    assert not verify_password("anything", "")
    assert not verify_password("anything", "not-a-valid-format")
    assert not verify_password("anything", "md5$1$deadbeef$deadbeef")


@pytest.mark.asyncio
async def test_session_token_unique_and_hashable():
    first = new_session_token()
    second = new_session_token()
    assert first != second
    assert len(first) >= 32
    digest = hash_token(first)
    assert digest != first
    assert len(digest) == 64
