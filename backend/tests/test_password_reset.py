
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import auth_routes
from app.db.session import get_db


@pytest.fixture
def client():
    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_forgot_password_success(client, monkeypatch):
    called = {"value": False}

    def fake_request_password_reset(db, email):
        called["value"] = True
        assert email == "lawyer@example.com"

    monkeypatch.setattr(
        auth_routes,
        "request_password_reset",
        fake_request_password_reset,
    )

    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "lawyer@example.com"},
    )

    assert response.status_code == 200
    assert called["value"] is True
    assert "password reset code" in response.json()["message"]


def test_forgot_password_unknown_account_uses_same_response(
    client, monkeypatch
):
    def fake_request_password_reset(db, email):
        return None

    monkeypatch.setattr(
        auth_routes,
        "request_password_reset",
        fake_request_password_reset,
    )

    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 200


def test_forgot_password_invalid_email_rejected(client):
    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422


def test_reset_password_success(client, monkeypatch):
    called = {"value": False}

    def fake_reset_password(db, email, otp, new_password):
        called["value"] = True
        assert email == "lawyer@example.com"
        assert otp == "123456"
        assert new_password == "NewPassword123"

    monkeypatch.setattr(
        auth_routes,
        "reset_password",
        fake_reset_password,
    )

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "lawyer@example.com",
            "otp": "123456",
            "new_password": "NewPassword123",
            "confirm_password": "NewPassword123",
        },
    )

    assert response.status_code == 200
    assert called["value"] is True
    assert "successfully" in response.json()["message"]


def test_reset_password_invalid_otp_rejected(client):
    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "lawyer@example.com",
            "otp": "123",
            "new_password": "NewPassword123",
            "confirm_password": "NewPassword123",
        },
    )

    assert response.status_code == 422


def test_reset_password_mismatched_passwords_rejected(client):
    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "lawyer@example.com",
            "otp": "123456",
            "new_password": "NewPassword123",
            "confirm_password": "DifferentPassword123",
        },
    )

    assert response.status_code == 422


def test_reset_password_invalid_code_returns_bad_request(
    client, monkeypatch
):
    def fake_reset_password(db, email, otp, new_password):
        raise ValueError("Invalid email or verification code.")

    monkeypatch.setattr(
        auth_routes,
        "reset_password",
        fake_reset_password,
    )

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "lawyer@example.com",
            "otp": "123456",
            "new_password": "NewPassword123",
            "confirm_password": "NewPassword123",
        },
    )

    assert response.status_code == 400
