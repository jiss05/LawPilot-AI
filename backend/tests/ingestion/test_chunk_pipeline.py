"""
Acceptance criterion: "Chunk metadata is stored correctly."
Plus: automatic processing after upload, and the shared storage folder.

Like test_ingestion_pipeline.py, these use a small FakeSession instead of
PostgreSQL so they run anywhere in a second. (The same flow was also run
against a real PostgreSQL database while developing; see the README.)
"""

import uuid

import pytest
from sqlalchemy.sql.dml import Delete

from app.ingestion import tasks
from app.ingestion.chunk_pipeline import chunk_uuid, run_chunking
from app.ingestion.extractor import DocumentExtractor
from app.ingestion.pipeline import DocumentStatus, JobStatus, run_extraction
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion

from .helpers import make_statute_pdf


class FakeSession:
    """Just enough of a SQLAlchemy Session for the pipelines."""

    def __init__(self, *objects):
        self.objects = {(type(o), o.id): o for o in objects}
        self.added, self.deletes = [], []
        self.commits = self.rollbacks = 0

    def get(self, model, key):
        return self.objects.get((model, key))

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def add_all(self, objs):
        for obj in objs:
            self.add(obj)

    def scalars(self, statement):
        """Only used for "this document's chunks, in order"."""
        return iter(self.chunks())

    def execute(self, statement):
        assert isinstance(statement, Delete)
        self.deletes.append(statement)
        # emulate DELETE ... WHERE knowledge_document_id = X
        self.added = [o for o in self.added if not isinstance(o, DocumentChunk)]

    def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def refresh(self, obj):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def chunks(self):
        return sorted((o for o in self.added if isinstance(o, DocumentChunk)), key=lambda c: c.chunk_index)

    def jobs(self):
        return [o for o in self.added if isinstance(o, IngestionJob)]


@pytest.fixture
def world(settings, tmp_path):
    """A source, an edition, a stored statute PDF and its document row."""
    settings = settings.model_copy(update={"ocr_enabled": False})
    settings.storage_dir.mkdir(parents=True)
    source = KnowledgeSource(id=uuid.uuid4(), title="Sample Contract Act, 1872", source_type="statute",
                             jurisdiction="India", trust_tier="official")
    version = SourceVersion(id=uuid.uuid4(), source_id=source.id, content_hash="x", status="pending")
    doc_id = uuid.uuid4()
    make_statute_pdf(settings.storage_dir / f"{doc_id}.pdf")
    document = KnowledgeDocument(
        id=doc_id, source_version_id=version.id, filename="sample_act.pdf", file_type="application/pdf",
        storage_key=f"{doc_id}.pdf", sha256="", uploaded_by=uuid.uuid4(),
        processing_status=DocumentStatus.UPLOADED, visibility="internal",
    )
    db = FakeSession(source, version, document)
    return db, document, source, version, settings


def extract_then_chunk(db, document, settings):
    extractor = DocumentExtractor(settings)
    run_extraction(db, document.id, document.uploaded_by, extractor=extractor, settings=settings)
    return run_chunking(db, document.id, document.uploaded_by, settings=settings)


def test_chunks_saved_with_source_page_and_section_references(world):
    db, document, source, version, settings = world
    job = extract_then_chunk(db, document, settings)

    assert job.status == JobStatus.COMPLETED
    assert document.processing_status == DocumentStatus.CHUNKED
    chunks = db.chunks()
    assert len(chunks) == job.counts["chunks"] >= 5

    for index, row in enumerate(chunks):
        assert row.chunk_index == index
        assert row.id == chunk_uuid(document.id, index)          # stable id
        assert row.knowledge_document_id == document.id           # the file
        assert row.source_version_id == version.id                # the edition
        assert row.token_count > 0 and row.text.strip()
        meta = row.chunk_metadata
        assert meta["document_id"] == str(document.id)
        assert meta["source_id"] == str(source.id)
        assert meta["source_title"] == "Sample Contract Act, 1872"
        assert meta["page_start"] == row.page_number
        assert meta["page_end"] >= meta["page_start"]
        assert meta["extraction_methods"] == ["native"]
        assert {"heading_path", "part", "parts", "chunker_version", "unit_kind"} <= meta.keys()

    s73 = [c for c in chunks if c.section_ref == "Section 73"]
    assert s73[0].page_number == 2 and s73[-1].chunk_metadata["page_end"] == 3
    assert s73[0].chunk_metadata["heading_path"][0] == "CHAPTER VI"


def test_job_rows_link_to_the_document(world):
    db, document, *_ , settings = world
    extract_then_chunk(db, document, settings)
    jobs = db.jobs()
    assert [j.counts["stage"] for j in jobs] == ["text_extraction", "chunking"]
    assert all(j.knowledge_document_id == document.id for j in jobs)
    assert jobs[1].counts["chunker_version"] == "1.0"
    assert jobs[1].counts["cleaning"]["edge_lines_removed"] >= 6  # 3 headers + 3 page numbers


def test_rerunning_replaces_chunks_and_keeps_ids(world):
    db, document, *_ , settings = world
    extract_then_chunk(db, document, settings)
    first_ids = [c.id for c in db.chunks()]
    run_chunking(db, document.id, document.uploaded_by, settings=settings)
    assert [c.id for c in db.chunks()] == first_ids  # same ids, no duplicates
    assert len(db.deletes) == 2


def test_chunking_before_extraction_is_recorded_as_failure(world):
    db, document, *_ , settings = world
    job = run_chunking(db, document.id, document.uploaded_by, settings=settings)
    assert job.status == JobStatus.FAILED
    assert job.error_summary.startswith("[NO_EXTRACTION_OUTPUT]")
    assert document.processing_status == DocumentStatus.CHUNKING_FAILED
    assert db.chunks() == []


def test_unexpected_error_rolls_back_and_is_recorded(world, monkeypatch):
    db, document, *_ , settings = world
    run_extraction(db, document.id, document.uploaded_by, extractor=DocumentExtractor(settings), settings=settings)

    def boom(*args, **kwargs):
        raise KeyError("bug")

    monkeypatch.setattr("app.ingestion.chunk_pipeline.chunk_document", boom)
    job = run_chunking(db, document.id, document.uploaded_by, settings=settings)
    assert job.error_summary == "[UNEXPECTED_ERROR] Unexpected KeyError during chunking."
    assert db.rollbacks >= 1


# ---------------------------------------------------------------------------
# Automatic processing after upload
# ---------------------------------------------------------------------------
class FakeJob:
    def __init__(self, stage, status):
        self.status, self.counts = status, {"stage": stage}


def test_process_document_runs_each_stage_only_after_the_previous_succeeds(monkeypatch):
    calls = []
    monkeypatch.setattr("app.ingestion.activation.run_activation", lambda db, d, u: calls.append("activate") or FakeJob("activation", JobStatus.COMPLETED))
    monkeypatch.setattr(tasks, "_mark_edition_failed_if_needed", lambda db, d: calls.append("mark_failed"))
    monkeypatch.setattr(tasks, "run_extraction", lambda db, d, u: calls.append("extract") or FakeJob("text_extraction", JobStatus.COMPLETED))
    monkeypatch.setattr("app.ingestion.chunk_pipeline.run_chunking", lambda db, d, u: calls.append("chunk") or FakeJob("chunking", JobStatus.COMPLETED))
    monkeypatch.setattr("app.ingestion.index_pipeline.run_indexing", lambda db, d, u: calls.append("index") or FakeJob("indexing", JobStatus.COMPLETED))
    tasks.process_document(None, uuid.uuid4(), uuid.uuid4())
    assert calls == ["extract", "chunk", "index", "activate"]

    calls.clear()
    monkeypatch.setattr("app.ingestion.chunk_pipeline.run_chunking", lambda db, d, u: calls.append("chunk") or FakeJob("chunking", JobStatus.FAILED))
    tasks.process_document(None, uuid.uuid4(), uuid.uuid4())
    assert calls == ["extract", "chunk", "mark_failed"]  # stops; edition marked failed

    calls.clear()
    monkeypatch.setattr(tasks, "run_extraction", lambda db, d, u: calls.append("extract") or FakeJob("text_extraction", JobStatus.FAILED))
    tasks.process_document(None, uuid.uuid4(), uuid.uuid4())
    assert calls == ["extract", "mark_failed"]  # corrupted/empty files are not chunked


def test_background_task_never_raises(monkeypatch):
    import app.db.session as session_module

    def broken_session():
        raise RuntimeError("database is down")

    monkeypatch.setattr(session_module, "SessionLocal", broken_session)
    tasks.process_uploaded_document(uuid.uuid4(), uuid.uuid4())  # logs, does not raise


# ---------------------------------------------------------------------------
# Upload saves into the same folder extraction reads from
# ---------------------------------------------------------------------------
def test_upload_and_extraction_share_the_storage_folder(settings, monkeypatch, tmp_path):
    from app.ingestion.storage import resolve_storage_path
    from app.services import knowledge_source_service as service

    monkeypatch.setattr(service, "get_ingestion_settings", lambda: settings)
    pdf = make_statute_pdf(tmp_path / "upload.pdf").read_bytes()
    db = FakeSession()
    source, document = service.register_legal_source(
        db, title="Act", source_type="statute", jurisdiction="India", trust_tier="official",
        publisher=None, canonical_url=None, version_label=None, published_at=None,
        original_filename="act.pdf", file_content=pdf, uploaded_by=uuid.uuid4(),
    )
    assert document.storage_key == f"{document.id}.pdf"           # relative key
    stored = resolve_storage_path(document.storage_key, settings)  # what extraction will open
    assert stored.read_bytes() == pdf
    assert document.processing_status == "pending"
    version = next(o for o in db.added if isinstance(o, SourceVersion))
    assert version.status == "pending"                             # not active until processed
