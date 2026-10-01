"""密码哈希与令牌的单元测试，不依赖数据库。"""

from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import BusinessError, ErrorCode
from app.core.security import (
    PBKDF2_ITERATIONS,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.timeutil import utc_now


def test_password_hash_format_matches_legacy_scheme() -> None:
    stored = hash_password("测试口令-1234")

    scheme, salt, digest = stored.split("$")
    assert scheme == f"pbkdf2:sha256:{PBKDF2_ITERATIONS}"
    assert len(salt) == 32
    assert len(digest) == 64


def test_password_round_trip_and_rejection() -> None:
    stored = hash_password("正确口令")

    assert verify_password("正确口令", stored)
    assert not verify_password("错误口令", stored)


def test_same_password_produces_different_hashes() -> None:
    assert hash_password("同一个口令") != hash_password("同一个口令")


def test_malformed_hash_is_rejected_without_exception() -> None:
    assert not verify_password("任意", "not-a-valid-hash")
    assert not verify_password("任意", "")


def test_access_token_round_trip() -> None:
    token, token_id, _ = create_access_token(7)

    payload = decode_token(token, "access")

    assert payload["sub"] == "7"
    assert payload["jti"] == token_id
    assert payload["type"] == "access"


def test_token_type_mismatch_is_rejected() -> None:
    token, _, _ = create_access_token(7)

    with pytest.raises(BusinessError) as exc:
        decode_token(token, "refresh")

    assert exc.value.code == ErrorCode.NOT_AUTHENTICATED


def test_expired_token_reports_40101() -> None:
    settings = get_settings()
    now = utc_now()
    expired = jwt.encode(
        {
            "sub": "1",
            "type": "access",
            "jti": "expired",
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(BusinessError) as exc:
        decode_token(expired, "access")

    assert exc.value.code == ErrorCode.TOKEN_EXPIRED


def test_token_signed_with_other_secret_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "1", "type": "access", "jti": "forged", "exp": utc_now() + timedelta(minutes=5)},
        "another-secret-with-enough-length-for-hs256",
        algorithm=get_settings().jwt_algorithm,
    )

    with pytest.raises(BusinessError) as exc:
        decode_token(forged, "access")

    assert exc.value.code == ErrorCode.NOT_AUTHENTICATED
