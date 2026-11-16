"""
Background processing started automatically after an upload.

The upload API (POST /api/v1/knowledge-sources) answers the admin
straight away, then FastAPI calls `process_uploaded_document()` in the
background:

    upload saved  ->  extraction (+ OCR)  ->  cleaning + chunking  ->  embeddings + Qdrant
                      run_extraction()        run_chunking()          run_indexing()

Each stage only runs if the previous one completed. Every outcome is recorded in
`ingestion_jobs` (one row per stage) and `knowledge_documents.processing_status`,
so the admin can watch progress:

    pending -> extracting -> extracted -> chunking -> chunked -> indexing -> indexed
                   |                          |                     |
                   +-> empty / corrupted /    +-> chunking_failed   +-> indexing_failed
                       extraction_failed

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
    from app.ingestion.index_pipeline import run_indexing

    stages = [run_extraction, run_chunking, run_indexing]
    jobs = []
    for stage in stages:
        jobs.append(stage(db, document_id, initiated_by))
        if jobs[-1].status != JobStatus.COMPLETED:
            break  # a failed stage stops the pipeline; the failure is recorded
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
