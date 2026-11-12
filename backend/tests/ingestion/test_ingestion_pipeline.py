"""
Acceptance criterion: "Extraction failures are recorded."

`run_extraction` talks to the database. Our models use PostgreSQL-only
types (UUID, JSONB), so instead of a real database these tests use a tiny
`FakeSession` that stores objects in a dictionary and counts commits.
That lets us test the pipeline's LOGIC (what gets written, in which
status) quickly and without Docker. A real Postgres integration test can
be added once the upload story is done.
"""

import json
import uuid

import pytest

from app.ingestion.extractor import DocumentExtractor
from app.ingestion.file_validation import compute_sha256
from app.ingestion.pipeline import DocumentStatus, JobStatus, run_extraction
from app.ingestion.storage import load_extraction_result
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.source_version import SourceVersion

from .helpers import LEGAL_TEXT, make_pdf


class FakeSession:
    def __init__(self, *objects):
        self.objects = {(type(o), o.id): o for o in objects}
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.status_at_commit = []  # snapshot of statuses at each commit

    def get(self, model, key):
        return self.objects.get((model, key))

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()  # the DB default would do this
        self.added.append(obj)

    def commit(self):
        self.commits += 1
        jobs = [o for o in self.added if isinstance(o, IngestionJob)]
        self.status_at_commit.append(jobs[-1].status if jobs else None)

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def setup(settings, fake_ocr):
    """Create a SourceVersion + KnowledgeDocument and a stored file."""
    settings.storage_dir.mkdir(parents=True)
    source_version = SourceVersion(
        id=uuid.uuid4(), source_id=uuid.uuid4(), content_hash="x", status="active"
    )
    admin_id = uuid.uuid4()

    def make_document(storage_key, sha256="", status=DocumentStatus.UPLOADED):
        return KnowledgeDocument(
            id=uuid.uuid4(),
            source_version_id=source_version.id,
            filename=storage_key,
            file_type=storage_key.rsplit(".", 1)[-1],
            storage_key=storage_key,
            sha256=sha256,
            uploaded_by=admin_id,
            processing_status=status,
            visibility="public",
        )

    extractor = DocumentExtractor(settings, ocr_engine=fake_ocr)
    return settings, source_version, admin_id, make_document, extractor


def test_successful_extraction_is_recorded(setup):
    settings, source_version, admin_id, make_document, extractor = setup
    stored = make_pdf(settings.storage_dir / "act.pdf", [LEGAL_TEXT, None])
    document = make_document("act.pdf", sha256=compute_sha256(stored))
    db = FakeSession(source_version, document)

    job = run_extraction(db, document.id, admin_id, extractor=extractor, settings=settings)

    # job row
    assert job.status == JobStatus.COMPLETED
    assert job.initiated_by == admin_id               # FR-021: who started it
    assert job.source_id == source_version.source_id
    assert job.source_version_id == source_version.id
    assert job.started_at and job.finished_at and job.error_summary is None
    assert job.counts["document_id"] == str(document.id)
    assert job.counts["pages_total"] == 2 and job.counts["pages_ocr"] == 1

    # document row
    assert document.processing_status == DocumentStatus.EXTRACTED

    # "running" was committed BEFORE the work, "completed" after it
    assert db.status_at_commit == [JobStatus.RUNNING, JobStatus.COMPLETED]

    # page-by-page JSON saved and loadable, page references intact
    saved = load_extraction_result(document.id, settings)
    assert [p.page_number for p in saved.pages] == [1, 2]
    data = json.loads((settings.extracted_dir / f"{document.id}.extracted.json").read_text("utf-8"))
    assert data["document_id"] == str(document.id)


@pytest.mark.parametrize(
    "filename, content, expected_status, expected_code",
    [
        ("blank.txt", b"   ", DocumentStatus.EMPTY, "NO_TEXT_FOUND"),
        ("zero.pdf", b"", DocumentStatus.EMPTY, "EMPTY_FILE"),
        ("bad.pdf", b"%PDF-1.4 broken" * 10, DocumentStatus.CORRUPTED, "CORRUPTED_FILE"),
        ("fake.pdf", b"hello", DocumentStatus.CORRUPTED, "SIGNATURE_MISMATCH"),
        ("sheet.xlsx", b"PK..", DocumentStatus.EXTRACTION_FAILED, "UNSUPPORTED_FORMAT"),
    ],
)
def test_failures_are_recorded(setup, filename, content, expected_status, expected_code):
    settings, source_version, admin_id, make_document, extractor = setup
    (settings.storage_dir / filename).write_bytes(content)
    document = make_document(filename)
    db = FakeSession(source_version, document)

    job = run_extraction(db, document.id, admin_id, extractor=extractor, settings=settings)

    assert job.status == JobStatus.FAILED
    assert job.error_summary.startswith(f"[{expected_code}]")
    assert job.counts["error"]["code"] == expected_code
    assert job.finished_at is not None
    assert document.processing_status == expected_status
    assert db.status_at_commit[-1] == JobStatus.FAILED
    assert not (settings.extracted_dir / f"{document.id}.extracted.json").exists()


def test_missing_stored_file_is_recorded(setup):
    settings, source_version, admin_id, make_document, extractor = setup
    document = make_document("gone.pdf")
    job = run_extraction(FakeSession(source_version, document), document.id, admin_id,
                         extractor=extractor, settings=settings)
    assert job.counts["error"]["code"] == "FILE_NOT_FOUND"
    assert document.processing_status == DocumentStatus.EXTRACTION_FAILED


def test_path_traversal_storage_key_is_refused(setup):
    settings, source_version, admin_id, make_document, extractor = setup
    document = make_document("../../secrets.txt")
    job = run_extraction(FakeSession(source_version, document), document.id, admin_id,
                         extractor=extractor, settings=settings)
    assert job.status == JobStatus.FAILED
    assert "outside the document storage folder" in job.error_summary


def test_unexpected_error_is_recorded_without_stack_trace(setup):
    settings, source_version, admin_id, make_document, _ = setup
    make_pdf(settings.storage_dir / "act.pdf", [LEGAL_TEXT])
    document = make_document("act.pdf")

    class ExplodingExtractor:
        def extract(self, path, expected_sha256=None):
            raise KeyError("internal detail")

    db = FakeSession(source_version, document)
    job = run_extraction(db, document.id, admin_id,
                         extractor=ExplodingExtractor(), settings=settings)
    assert job.status == JobStatus.FAILED
    assert job.error_summary == "[UNEXPECTED_ERROR] Unexpected KeyError during extraction."
    assert "Traceback" not in job.error_summary
    assert db.rollbacks == 1


def test_unknown_document_id_raises(settings):
    with pytest.raises(ValueError):
        run_extraction(FakeSession(), uuid.uuid4(), uuid.uuid4(), settings=settings)
