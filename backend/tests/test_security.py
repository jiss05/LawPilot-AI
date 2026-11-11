
from datetime import timedelta

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


def test_password_hashing():
    password = "TestPassword123"

    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)


def test_wrong_password_rejected():
    hashed = hash_password("CorrectPassword123")

    assert not verify_password("WrongPassword123", hashed)


def test_jwt_creation_and_decoding():
    token = create_access_token("test-user-id")

    payload = decode_access_token(token)

    assert payload is not None
    assert payload["sub"] == "test-user-id"
    assert "exp" in payload


def test_expired_jwt_rejected():
    token = create_access_token(
        "test-user-id",
        expires_delta=timedelta(seconds=-1),
    )

    payload = decode_access_token(token)

    assert payload is None
