"""Deleting a legal source: order of operations and API errors (no database)."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.ingestion.config import IngestionSettings
from app.main import app
from app.models.knowledge_source import KnowledgeSource
from app.services import source_deletion
from app.services.source_deletion import (
    SourceBusy,
    SourceNotFound,
    VectorStoreUnavailable,
    delete_legal_source,
)


def doc(status="indexed"):
    return SimpleNamespace(id=uuid.uuid4(), filename="act.pdf", storage_key=f"{uuid.uuid4()}.pdf",
                           processing_status=status)


class FakeDB:
    """Answers the lookups; records every write."""

    def __init__(self, source, version_ids, documents, chunks=7):
        self.source, self.version_ids, self.documents, self.chunks = source, version_ids, documents, chunks
        self.executed, self.committed, self.rolled_back, self.added = [], False, False, []
        self._scalars = [version_ids, documents]

    def get(self, model, key):
        return self.source if model is KnowledgeSource else None

    def scalars(self, statement):
        return SimpleNamespace(all=lambda: self._scalars.pop(0))

    def scalar(self, statement):
        return self.chunks

    def execute(self, statement):
        self.executed.append(statement)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeStore:
    def __init__(self, fail=False):
        self.fail, self.deleted = fail, []

    def delete_document(self, document_id):
        if self.fail:
            raise ConnectionError("qdrant down")
        self.deleted.append(document_id)


@pytest.fixture
def settings(tmp_path):
    return IngestionSettings(_env_file=None, storage_dir=tmp_path / "docs", extracted_dir=tmp_path / "ext")


def test_deletes_vectors_rows_files_and_audits(settings):
    docs = [doc(), doc()]
    settings.storage_dir.mkdir()
    settings.extracted_dir.mkdir()
    for d in docs:
        (settings.storage_dir / d.storage_key).write_bytes(b"%PDF-")
        (settings.extracted_dir / f"{d.id}.extracted.json").write_text("{}")
    source = SimpleNamespace(id=uuid.uuid4(), title="Indian Contract Act")
    db, store = FakeDB(source, [uuid.uuid4()], docs), FakeStore()

    result = delete_legal_source(db, source.id, actor_user_id=uuid.uuid4(), settings=settings, vector_store=store)

    assert store.deleted == [d.id for d in docs]
    assert db.committed and not db.rolled_back
    assert len(db.executed) >= 6                  # citations, chunks, jobs, documents, versions, source
    assert db.added[0].action == "knowledge_source.deleted"
    assert db.added[0].metadata_json == {"title": "Indian Contract Act", "versions": 1, "documents": 2,
                                         "chunks": 7, "forced": False}
    assert (result.documents, result.chunks, result.files_deleted) == (2, 7, 4)
    assert not any(settings.storage_dir.iterdir()) and not any(settings.extracted_dir.iterdir())


def test_qdrant_failure_deletes_nothing(settings):
    source = SimpleNamespace(id=uuid.uuid4(), title="X")
    db = FakeDB(source, [uuid.uuid4()], [doc()])
    with pytest.raises(VectorStoreUnavailable):
        delete_legal_source(db, source.id, actor_user_id=uuid.uuid4(), settings=settings,
                            vector_store=FakeStore(fail=True))
    assert db.executed == [] and not db.committed


def test_busy_document_blocks_unless_forced(settings):
    source = SimpleNamespace(id=uuid.uuid4(), title="X")
    with pytest.raises(SourceBusy):
        delete_legal_source(FakeDB(source, [uuid.uuid4()], [doc("indexing")]), source.id,
                            actor_user_id=uuid.uuid4(), settings=settings, vector_store=FakeStore())
    db = FakeDB(source, [uuid.uuid4()], [doc("indexing")])
    delete_legal_source(db, source.id, actor_user_id=uuid.uuid4(), settings=settings,
                        vector_store=FakeStore(), force=True)
    assert db.committed and db.added[0].metadata_json["forced"] is True


def test_missing_source(settings):
    with pytest.raises(SourceNotFound):
        delete_legal_source(FakeDB(None, [], []), uuid.uuid4(), actor_user_id=uuid.uuid4(),
                            settings=settings, vector_store=FakeStore())


def test_database_error_rolls_back(settings):
    source = SimpleNamespace(id=uuid.uuid4(), title="X")
    db = FakeDB(source, [uuid.uuid4()], [doc()])

    def boom(statement):
        raise RuntimeError("db down")

    db.execute = boom
    with pytest.raises(RuntimeError):
        delete_legal_source(db, source.id, actor_user_id=uuid.uuid4(), settings=settings,
                            vector_store=FakeStore())
    assert db.rolled_back and not db.committed


# ------------------------------------------------------------------ API
def user(role):
    return SimpleNamespace(id=uuid.uuid4(), is_active=True, email_verified=True,
                           role_assignments=[SimpleNamespace(role=SimpleNamespace(code=role))])


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["CLIENT", "LAWYER", "JUDGE"])
def test_only_admin_can_delete(client, role):
    app.dependency_overrides[get_current_user] = lambda: user(role)
    assert client.delete(f"/api/v1/knowledge-sources/{uuid.uuid4()}").status_code == 403


@pytest.mark.parametrize("error, code", [
    (SourceNotFound("x"), 404), (SourceBusy("act.pdf"), 409), (VectorStoreUnavailable(), 503),
])
def test_errors_are_mapped(client, monkeypatch, error, code):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(source_deletion, "delete_legal_source", fail)
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")
    r = client.delete(f"/api/v1/knowledge-sources/{uuid.uuid4()}")
    assert r.status_code == code
    assert "Traceback" not in r.text


def test_success_returns_counts(client, monkeypatch):
    sid = uuid.uuid4()
    monkeypatch.setattr(source_deletion, "delete_legal_source", lambda *a, **k: source_deletion.DeletionResult(
        source_id=sid, title="Constitution of India", versions=1, documents=1, chunks=812, files_deleted=2))
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")
    body = client.delete(f"/api/v1/knowledge-sources/{sid}").json()
    assert body["chunks"] == 812 and body["title"] == "Constitution of India"
