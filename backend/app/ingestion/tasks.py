"""
Background processing started automatically after an upload.

The upload API (POST /api/v1/knowledge-sources) answers the admin
straight away, then FastAPI calls `process_uploaded_document()` in the
background:

    upload saved -> extraction (+OCR) -> cleaning + chunking -> embeddings + Qdrant -> checks + activation
                    run_extraction()     run_chunking()         run_indexing()         run_activation()

Each stage only runs if the previous one completed. Every outcome is recorded in
`ingestion_jobs` (one row per stage) and `knowledge_documents.processing_status`,
so the admin can watch progress:

    pending -> extracting -> extracted -> chunking -> chunked -> indexing -> indexed -> completed
                   |                          |                     |                    |
                   +-> empty / corrupted /    +-> chunking_failed   +-> indexing_failed  +-> activation_failed
                       extraction_failed

`completed` documents of an `active` edition are what search returns.

WHY A NEW DATABASE SESSION?
The request's session is closed once the response is sent, so the
background task must open its own (`SessionLocal()`), and must close it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.ingestion.pipeline import JobStatus, run_extraction

logger = logging.getLogger(__name__)


def process_document(db: Session, document_id: UUID, initiated_by: UUID) -> list:
    """
    Run every ingestion stage built so far on one document.
    Returns the IngestionJob rows, in order. Used by the background task
    and by the CLI `run` command.
    """
    from app.ingestion.chunk_pipeline import run_chunking
    from app.ingestion.activation import run_activation
    from app.ingestion.index_pipeline import run_indexing

    stages = [run_extraction, run_chunking, run_indexing, run_activation]
    jobs = []
    for stage in stages:
        jobs.append(stage(db, document_id, initiated_by))
        if jobs[-1].status != JobStatus.COMPLETED:
            # A failed stage stops the pipeline; the failure is already
            # recorded on the job and the document.
            _mark_edition_failed_if_needed(db, document_id)
            break
    return jobs


def process_uploaded_document(document_id: UUID, initiated_by: UUID) -> None:
    """Entry point for FastAPI BackgroundTasks. Never raises."""
    # Imported here: app.db.session needs DATABASE_URL when imported.
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            jobs = process_document(db, document_id, initiated_by)
            logger.info(
                "Processed document %s: %s",
                document_id,
                ", ".join(f"{j.counts.get('stage')}={j.status}" for j in jobs),
            )
    except Exception:
        # A background task has nobody to report to, so log the full error.
        # (run_extraction/run_chunking already record their own failures;
        # this only catches problems such as the database being down.)
        logger.exception("Background processing failed for document %s", document_id)



def _mark_edition_failed_if_needed(db: Session, document_id: UUID) -> None:
    """
    If a brand-new (pending) edition's document failed processing, mark the
    edition `failed` so the admin's version list shows it clearly. Editions
    that are already active, superseded or withdrawn are never touched.
    """
    from app.ingestion.activation import VersionStatus
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.source_version import SourceVersion

    document = db.get(KnowledgeDocument, document_id)
    version = db.get(SourceVersion, document.source_version_id) if document else None
    if version is not None and version.status == VersionStatus.PENDING:
        version.status = VersionStatus.FAILED
        db.commit()
