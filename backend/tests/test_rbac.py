import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies import get_current_user
from app.db.session import get_db


DASHBOARDS = {
    "CLIENT": "/api/v1/client/dashboard",
    "LAWYER": "/api/v1/lawyer/dashboard",
    "JUDGE": "/api/v1/judge/dashboard",
    "ADMIN": "/api/v1/admin/dashboard",
}


def make_mock_user(role: str):
    """Create a mock user with one assigned application role."""

    return SimpleNamespace(
        id=uuid.uuid4(),
        is_active=True,
        role_assignments=[
            SimpleNamespace(
                role=SimpleNamespace(code=role)
            )
        ],
    )


@pytest.fixture
def client():
    """Create a test client without connecting to PostgreSQL."""

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "role, endpoint",
    DASHBOARDS.items(),
)
def test_correct_role_can_access_dashboard(client, role, endpoint):
    """Each role should access its own dashboard."""

    app.dependency_overrides[get_current_user] = (
        lambda: make_mock_user(role)
    )

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json()["role"] == role


@pytest.mark.parametrize(
    "role, endpoint",
    DASHBOARDS.items(),
)
def test_wrong_role_cannot_access_dashboard(client, role, endpoint):
    """A user with a different role must receive HTTP 403."""

    other_role = next(
        candidate
        for candidate in DASHBOARDS
        if candidate != role
    )

    app.dependency_overrides[get_current_user] = (
        lambda: make_mock_user(other_role)
    )

    response = client.get(endpoint)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "role, endpoint",
    DASHBOARDS.items(),
)
def test_unauthenticated_user_cannot_access_dashboard(
    client,
    role,
    endpoint,
):
    """Requests without a JWT must receive HTTP 401."""

    response = client.get(endpoint)

    assert response.status_code == 401