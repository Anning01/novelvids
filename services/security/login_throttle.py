"""有界、进程内的登录限流器。

项目线上保持单 worker；如部署边缘 WAF，可由其负责第一层 IP 限流，本服务始终
提供不依赖供应商的应用层保护。所有状态都有时间窗口和容量上限，避免攻击者制造
无限内存增长。
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import math
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable, Deque

from fastapi import HTTPException, Request

from config import settings


@dataclass(frozen=True)
class LoginAttempt:
    ip: str
    principal_key: str


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._attempts: OrderedDict[str, Deque[float]] = OrderedDict()
        self._failures: OrderedDict[str, Deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def before_attempt(self, request: Request, username: str) -> LoginAttempt:
        ip = client_ip(request)
        principal_key = self._principal_key(ip, username)
        attempt = LoginAttempt(ip=ip, principal_key=principal_key)
        if not settings.LOGIN_RATE_LIMIT_ENABLED:
            return attempt

        now = self._clock()
        async with self._lock:
            ip_events = self._events(
                self._attempts,
                ip,
                now,
                settings.LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS,
            )
            self._reject_if_limited(
                ip_events,
                settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
                settings.LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS,
                now,
            )
            failure_events = self._events(
                self._failures,
                principal_key,
                now,
                settings.LOGIN_RATE_LIMIT_FAILURE_WINDOW_SECONDS,
            )
            self._reject_if_limited(
                failure_events,
                settings.LOGIN_RATE_LIMIT_FAILURES,
                settings.LOGIN_RATE_LIMIT_FAILURE_WINDOW_SECONDS,
                now,
            )
            ip_events.append(now)
            self._trim_capacity(self._attempts)
            self._trim_capacity(self._failures)
        return attempt

    async def record_failure(self, attempt: LoginAttempt) -> None:
        if not settings.LOGIN_RATE_LIMIT_ENABLED:
            return
        now = self._clock()
        async with self._lock:
            events = self._events(
                self._failures,
                attempt.principal_key,
                now,
                settings.LOGIN_RATE_LIMIT_FAILURE_WINDOW_SECONDS,
            )
            events.append(now)
            self._trim_capacity(self._failures)

    async def record_success(self, attempt: LoginAttempt) -> None:
        async with self._lock:
            self._failures.pop(attempt.principal_key, None)

    async def reset(self) -> None:
        """清空进程内状态；用于测试和受控维护。"""
        async with self._lock:
            self._attempts.clear()
            self._failures.clear()

    @staticmethod
    def _principal_key(ip: str, username: str) -> str:
        normalized = username.strip().casefold().encode("utf-8")
        digest = hashlib.sha256(normalized).hexdigest()
        return f"{ip}:{digest}"

    @staticmethod
    def _reject_if_limited(
        events: Deque[float], limit: int, window_seconds: int, now: float
    ) -> None:
        if len(events) < limit:
            return
        retry_after = max(1, math.ceil(window_seconds - (now - events[0])))
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    @staticmethod
    def _events(
        store: OrderedDict[str, Deque[float]],
        key: str,
        now: float,
        window_seconds: int,
    ) -> Deque[float]:
        events = store.setdefault(key, deque())
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        store.move_to_end(key)
        return events

    @staticmethod
    def _trim_capacity(store: OrderedDict[str, Deque[float]]) -> None:
        while len(store) > settings.LOGIN_RATE_LIMIT_MAX_KEYS:
            store.popitem(last=False)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer

    forwarded = request.headers.get("CF-Connecting-IP", "").strip()
    if not forwarded:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer


def _is_trusted_proxy(peer: str) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for raw in settings.TRUSTED_PROXY_NETWORKS:
        try:
            if address in ipaddress.ip_network(raw, strict=False):
                return True
        except ValueError:
            continue
    return False


login_throttle = LoginThrottle()
