"""GET /api/v1/health/ready reports database and Qdrant status (SCRUM-33)."""

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.ingestion import config as ingestion_config
from app.main import app


def test_ready_when_database_and_qdrant_are_up(db, monkeypatch):
    monkeypatch.setenv("INGESTION_QDRANT_URL", ":memory:")
    ingestion_config.get_ingestion_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()
        ingestion_config.get_ingestion_settings.cache_clear()
    body = response.json()
    assert response.status_code == 200, body
    assert body["checks"]["database"]["migration"]
    assert body["checks"]["vector_store"]["status"] == "ok"
    assert "X-Request-ID" in response.headers


def test_not_ready_when_qdrant_is_down(db, monkeypatch):
    monkeypatch.setenv("INGESTION_QDRANT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("INGESTION_QDRANT_TIMEOUT_SECONDS", "1")
    ingestion_config.get_ingestion_settings.cache_clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()
        ingestion_config.get_ingestion_settings.cache_clear()
    assert response.status_code == 503
    assert response.json()["checks"]["vector_store"]["status"] == "unavailable"
    assert "local_dev_password" not in response.text  # no secrets in health output
