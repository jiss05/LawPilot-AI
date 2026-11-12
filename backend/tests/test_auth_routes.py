from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import auth_routes
from app.db.session import get_db


@pytest.fixture
def client():
    """Create a test client without connecting to PostgreSQL."""

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_user():
    """Create a sample pending user for endpoint tests."""

    return SimpleNamespace(
        id=uuid4(),
        email="test@example.com",
        display_name="Test User",
        email_verified=False,
        is_active=False,
        created_at=datetime.now(timezone.utc),
    )


def test_successful_registration_sends_otp(client, mock_user, monkeypatch):
    def fake_register_user(db, user_data):
        return mock_user

    def fake_create_and_send_otp(db, user):
        return None

    monkeypatch.setattr(auth_routes, "register_user", fake_register_user)
    monkeypatch.setattr(
        auth_routes,
        "create_and_send_otp",
        fake_create_and_send_otp,
    )

    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Test User",
            "email": "test@example.com",
            "password": "TestPassword123",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "test@example.com"
    assert response.json()["email_verified"] is False
    assert "verification code" in response.json()["message"]


def test_duplicate_email_rejected(client, monkeypatch):
    def fake_register_user(db, user_data):
        raise ValueError("An account with this email already exists.")

    monkeypatch.setattr(auth_routes, "register_user", fake_register_user)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Test User",
            "email": "test@example.com",
            "password": "TestPassword123",
        },
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_successful_email_verification(client, mock_user, monkeypatch):
    mock_user.email_verified = True
    mock_user.is_active = True

    def fake_verify_email_otp(db, email, otp):
        assert email == "test@example.com"
        assert otp == "123456"
        return mock_user

    monkeypatch.setattr(
        auth_routes,
        "verify_email_otp",
        fake_verify_email_otp,
    )

    response = client.post(
        "/api/v1/auth/verify-email",
        json={"email": "test@example.com", "otp": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["email_verified"] is True


def test_invalid_email_verification_code_rejected(client, monkeypatch):
    def fake_verify_email_otp(db, email, otp):
        raise ValueError("Invalid email or verification code.")

    monkeypatch.setattr(
        auth_routes,
        "verify_email_otp",
        fake_verify_email_otp,
    )

    response = client.post(
        "/api/v1/auth/verify-email",
        json={"email": "test@example.com", "otp": "000000"},
    )

    assert response.status_code == 400


def test_resend_otp_endpoint(client, monkeypatch):
    called = {"value": False}

    def fake_resend_email_otp(db, email):
        called["value"] = True

    monkeypatch.setattr(
        auth_routes,
        "resend_email_otp",
        fake_resend_email_otp,
    )

    response = client.post(
        "/api/v1/auth/resend-otp",
        json={"email": "test@example.com"},
    )

    assert response.status_code == 200
    assert called["value"] is True


def test_successful_login(client, mock_user, monkeypatch):
    mock_user.email_verified = True
    mock_user.is_active = True

    def fake_authenticate_user(db, email, password):
        return mock_user

    def fake_create_user_token(user):
        return "mock-access-token"

    monkeypatch.setattr(
        auth_routes,
        "authenticate_user",
        fake_authenticate_user,
    )
    monkeypatch.setattr(
        auth_routes,
        "create_user_token",
        fake_create_user_token,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPassword123",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "mock-access-token"
    assert response.json()["token_type"] == "bearer"


def test_invalid_login_rejected(client, monkeypatch):
    def fake_authenticate_user(db, email, password):
        return None

    monkeypatch.setattr(
        auth_routes,
        "authenticate_user",
        fake_authenticate_user,
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "WrongPassword123",
        },
    )

    assert response.status_code == 401


def test_registration_rejects_short_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Test User",
            "email": "test@example.com",
            "password": "short",
        },
    )

    assert response.status_code == 422


def test_verification_rejects_non_six_digit_code(client):
    response = client.post(
        "/api/v1/auth/verify-email",
        json={"email": "test@example.com", "otp": "123"},
    )

    assert response.status_code == 422
