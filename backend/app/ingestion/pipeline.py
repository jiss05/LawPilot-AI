"""
Extraction step of the ingestion pipeline: the part that touches the database.

Acceptance criterion: "Extraction failures are recorded."
BRD FR-021: "record ingestion job status, ... processing results, and the
identity of the authorized person who initiated each ingestion operation."

WHAT `run_extraction()` DOES
----------------------------
    1. load the KnowledgeDocument row (and its SourceVersion)
    2. create an IngestionJob row: status "running", started_at, initiated_by
       and set the document's processing_status to "extracting"
       -> COMMIT, so an admin dashboard can already see the job running
    3. find the stored file and run the DocumentExtractor
    4a. success: save page JSON, document -> "extracted",
                 job -> "completed", counts = statistics
    4b. failure: document -> "empty" / "corrupted" / "extraction_failed",
                 job -> "failed", error_summary = "[CODE] message",
                 counts = statistics + error details
    5. finished_at = now -> COMMIT

Nothing is ever lost silently: every outcome ends as a row in
`ingestion_jobs`.

STATUS VALUES FOR knowledge_documents.processing_status
-------------------------------------------------------
The hybrid-search branch (`app/rag/types.py`) only searches documents whose
status is "ready" or "completed". Every status set here is deliberately
different, so a document that is only extracted (not yet chunked and
embedded) can never appear in search results.

NOTE: `ingestion_jobs` has no `document_id` column in the current schema,
so we store it inside `counts["document_id"]`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.errors import (
    CORRUPTED_ERROR_CODES,
    EMPTY_ERROR_CODES,
    ExtractionError,
    ExtractionErrorCode,
)
from app.ingestion.extraction_types import ExtractionMethod
from app.ingestion.extractor import DocumentExtractor
from app.ingestion.storage import resolve_storage_path, save_extraction_result
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.source_version import SourceVersion

logger = logging.getLogger(__name__)


class DocumentStatus:
    """Values for knowledge_documents.processing_status."""

    UPLOADED = "uploaded"            # set by the upload story
    EXTRACTING = "extracting"        # extraction in progress
    EXTRACTED = "extracted"          # text ready for cleaning/chunking
    EMPTY = "empty"                  # no readable content
    CORRUPTED = "corrupted"          # damaged / mismatched / encrypted
    EXTRACTION_FAILED = "extraction_failed"  # any other failure


class JobStatus:
    """Values for ingestion_jobs.status."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


STAGE = "text_extraction"


def _now() -> datetime:
    return datetime.now(timezone.utc)  # BRD §8: timestamps in UTC


def status_for_error(code: ExtractionErrorCode) -> str:
    """Map an error code to the document status shown to administrators."""
    if code in EMPTY_ERROR_CODES:
        return DocumentStatus.EMPTY
    if code in CORRUPTED_ERROR_CODES:
        return DocumentStatus.CORRUPTED
    return DocumentStatus.EXTRACTION_FAILED


def run_extraction(
    db: Session,
    document_id: UUID,
    initiated_by: UUID,
    *,
    extractor: DocumentExtractor | None = None,
    settings: IngestionSettings | None = None,
) -> IngestionJob:
    """
    Extract one stored document and record the outcome.

    Always returns the IngestionJob. Check `job.status` to see whether it
    worked. Raises only if the document id itself does not exist.
    """
    settings = settings or get_ingestion_settings()
    extractor = extractor or DocumentExtractor(settings)

    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise ValueError(f"KnowledgeDocument {document_id} does not exist.")
    source_version = db.get(SourceVersion, document.source_version_id)

    # ---- step 2: open the job and show "running" immediately -------------
    base_counts: dict[str, Any] = {"stage": STAGE, "document_id": str(document.id)}
    job = IngestionJob(
        source_id=source_version.source_id if source_version else None,
        source_version_id=document.source_version_id,
        status=JobStatus.RUNNING,
        started_at=_now(),
        initiated_by=initiated_by,
        counts=base_counts,
    )
    db.add(job)
    document.processing_status = DocumentStatus.EXTRACTING
    db.commit()

    # ---- steps 3-4: do the work --------------------------------------------
    try:
        path = resolve_storage_path(document.storage_key, settings)
        result = extractor.extract(path, expected_sha256=document.sha256)
        output_path = save_extraction_result(document.id, result, settings)

        document.processing_status = DocumentStatus.EXTRACTED
        job.status = JobStatus.COMPLETED
        # Assign a NEW dict: SQLAlchemy does not notice in-place changes
        # to a JSONB dict unless the column uses MutableDict.
        job.counts = {
            **base_counts,
            **result.summary(),
            "output_path": str(output_path),
        }
        logger.info(
            "Extracted document %s: %s pages (%s via OCR)",
            document.id,
            result.page_count,
            result.count_by_method(ExtractionMethod.OCR),
        )

    except ExtractionError as exc:
        # Expected, explainable failures: empty, corrupted, unsupported ...
        logger.warning("Extraction failed for document %s: %s", document.id, exc)
        document.processing_status = status_for_error(exc.code)
        job.status = JobStatus.FAILED
        job.error_summary = str(exc)
        job.counts = {**base_counts, "error": exc.to_dict()}

    except Exception as exc:
        # Unexpected failures (bugs, disk full ...). Log the full stack trace
        # for developers, but store only a short message in the database
        # (BRD §15: never expose stack traces).
        logger.exception("Unexpected error extracting document %s", document.id)
        # If the error came from the database, the session is unusable until
        # it is rolled back. The job row was already committed in step 2, so
        # rolling back loses nothing; SQLAlchemy reloads it on next access.
        db.rollback()
        error = ExtractionError(
            ExtractionErrorCode.UNEXPECTED_ERROR,
            f"Unexpected {type(exc).__name__} during extraction.",
        )
        document.processing_status = DocumentStatus.EXTRACTION_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(error)
        job.counts = {**base_counts, "error": error.to_dict()}

    # ---- step 5: close the job -----------------------------------------------
    job.finished_at = _now()
    db.commit()
    return job
