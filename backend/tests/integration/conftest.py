"""
Integration tests: real PostgreSQL + embedded Qdrant.

They run only when TEST_DATABASE_URL points at a migrated database, e.g.
the Docker one:

    # Git Bash, from backend/ (database must be migrated: alembic upgrade head)
    TEST_DATABASE_URL=postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai \
        pytest tests/integration -v

Each test runs inside a transaction that is ROLLED BACK at the end, so the
tests never leave data behind, even in your development database.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.ingestion.config import IngestionSettings

DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set TEST_DATABASE_URL to run integration tests")


@pytest.fixture(scope="session")
def engine():
    if not DATABASE_URL:
        pytest.skip("set TEST_DATABASE_URL to run integration tests")
    from sqlalchemy import create_engine

    import app.models  # noqa: F401  (registers all models)

    engine = create_engine(DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    """A session whose work is rolled back after the test."""
    from sqlalchemy.orm import Session

    connection = engine.connect()
    transaction = connection.begin()
    # "create_savepoint": the code under test may call commit()/rollback();
    # those act on a SAVEPOINT inside our outer transaction.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(
        _env_file=None,
        storage_dir=tmp_path / "documents",
        extracted_dir=tmp_path / "extracted",
        ocr_enabled=False,
        embedding_provider="hashing",
        embedding_dimension=64,
        qdrant_url=":memory:",
        qdrant_collection=f"it_{uuid.uuid4().hex[:12]}",
    )
