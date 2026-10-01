"""密码哈希与 JWT 令牌。

密码格式沿用单机版：pbkdf2:sha256:200000$salt$hash（编写报告 7.1）。
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import Settings, get_settings
from app.core.errors import BusinessError, ErrorCode
from app.core.timeutil import utc_now

PASSWORD_PREFIX = "pbkdf2:sha256"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    """生成密码哈希，格式与单机版一致，便于历史账号平滑升级。"""
    salt = secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"{PASSWORD_PREFIX}:{PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码，使用固定时间比较避免时序泄露。"""
    try:
        scheme, salt, expected = stored_hash.split("$")
        prefix, algorithm, iterations = scheme.split(":")
        if prefix != "pbkdf2":
            return False
        rounds = int(iterations)
    except (AttributeError, ValueError):
        return False

    digest = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt.encode("utf-8"), rounds)
    return hmac.compare_digest(digest.hex(), expected)


def _encode(
    subject: int,
    token_type: TokenType,
    expires_delta: timedelta,
    settings: Settings,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    now = utc_now()
    expires_at = now + expires_delta
    token_id = secrets.token_urlsafe(24)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": token_id,
        "iat": now,
        "exp": expires_at,
    }
    if extra:
        payload.update(extra)

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, token_id, expires_at


def create_access_token(user_id: int, settings: Settings | None = None) -> tuple[str, str, datetime]:
    settings = settings or get_settings()
    return _encode(
        user_id,
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
        settings,
    )


def create_refresh_token(user_id: int, settings: Settings | None = None) -> tuple[str, str, datetime]:
    settings = settings or get_settings()
    return _encode(
        user_id,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
        settings,
    )


def decode_token(token: str, expected_type: TokenType, settings: Settings | None = None) -> dict[str, Any]:
    """解析令牌并校验类型；过期与非法分别对应 40101 与 40100。"""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise BusinessError(ErrorCode.TOKEN_EXPIRED, "令牌已过期", 401) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "令牌无效", 401) from exc

    if payload.get("type") != expected_type:
        raise BusinessError(ErrorCode.NOT_AUTHENTICATED, "令牌类型不正确", 401)
    return payload
