"""
Chunking step of the ingestion pipeline: the part that touches the database.

Acceptance criteria:
  * "Each chunk maintains its source and page references."
  * "Chunk metadata is stored correctly."

WHAT `run_chunking()` DOES
--------------------------
    1. load the KnowledgeDocument, its SourceVersion and KnowledgeSource
    2. open an IngestionJob (stage "chunking"), document -> "chunking", COMMIT
    3. read the extraction JSON written by the extraction step
    4. clean -> detect structure -> chunk          (app/ingestion/chunking/)
    5. in ONE transaction: delete this document's old chunks, insert the
       new ones, document -> "chunked", job -> "completed"
    6. on failure: document -> "chunking_failed", job -> "failed" + reason

WHERE EACH PIECE OF CHUNK INFORMATION IS STORED (document_chunks)
-----------------------------------------------------------------
    id                    stable UUID (see chunk_uuid below)
    source_version_id     the EDITION the text belongs to
    knowledge_document_id the FILE it was cut from          (new column)
    chunk_index           0, 1, 2 ... order inside the file
    text                  the cleaned chunk text
    page_number           first page of the chunk (page_start)
    section_ref           "Section 73", "Para 12", "Paras 4-6", "Preamble"
    token_count           approximate tokens (chars / 4)
    metadata (JSONB)      everything else: page_end, heading_path, part of
                          parts, overlap, source title/type, extraction
                          method (native/OCR), chunker version ...

RE-RUNNING IS SAFE ("idempotent")
---------------------------------
Running chunking again for the same document replaces its chunks instead
of adding duplicates, and because chunk ids are derived from the document
id + position, the same chunk gets the same id every time.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ingestion.chunking.chunker import CHUNKER_VERSION, Chunk, chunk_document
from app.ingestion.chunking.structure import mode_for_source_type
from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import ExtractionMethod, ExtractionResult
from app.ingestion.pipeline import DocumentStatus, JobStatus, _now
from app.ingestion.storage import extraction_output_path, load_extraction_result
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion

logger = logging.getLogger(__name__)

STAGE = "chunking"


def chunk_uuid(document_id: UUID, chunk_index: int) -> UUID:
    """
    A deterministic id: the same document + the same position always gives
    the same UUID (uuid5 = a hash of the inputs). Qdrant points and citations
    will store this id, so it should not change when chunking is re-run
    with the same rules.
    """
    return uuid.uuid5(document_id, f"chunk-{chunk_index}")


def _page_info(result: ExtractionResult, chunk: Chunk) -> dict[str, Any]:
    """How the chunk's pages were read (native text vs OCR) and how confidently."""
    pages = [
        p for p in result.pages
        if chunk.page_start is not None
        and p.page_number is not None
        and chunk.page_start <= p.page_number <= (chunk.page_end or chunk.page_start)
    ]
    methods = sorted({p.method.value for p in pages}) or sorted({p.method.value for p in result.pages})
    confidences = [p.ocr_confidence for p in pages if p.method == ExtractionMethod.OCR and p.ocr_confidence]
    return {
        "extraction_methods": methods,
        "min_ocr_confidence": round(min(confidences), 3) if confidences else None,
    }


def build_chunk_rows(
    document: KnowledgeDocument,
    source: KnowledgeSource | None,
    result: ExtractionResult,
    chunks: list[Chunk],
) -> list[DocumentChunk]:
    """Turn Chunk objects into DocumentChunk database rows."""
    rows = []
    for chunk in chunks:
        metadata = {
            # --- source references ---
            "document_id": str(document.id),
            "source_id": str(source.id) if source else None,
            "source_title": source.title if source else None,
            "source_type": source.source_type if source else None,
            "filename": document.filename,
            # --- page and structure references ---
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "page_numbers_reliable": result.page_numbers_reliable,
            "heading_path": chunk.heading_path,
            "unit_kind": chunk.unit_kind,
            "part": chunk.part,
            "parts": chunk.parts,
            "overlap_tokens": chunk.overlap_tokens,
            "char_count": chunk.char_count,
            # --- how it was produced (for debugging and re-processing) ---
            **_page_info(result, chunk),
            "chunker_version": CHUNKER_VERSION,
        }
        rows.append(
            DocumentChunk(
                id=chunk_uuid(document.id, chunk.chunk_index),
                source_version_id=document.source_version_id,
                knowledge_document_id=document.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                page_number=chunk.page_start,
                section_ref=chunk.section_ref,
                token_count=chunk.token_count,
                chunk_metadata=metadata,
            )
        )
    return rows


def run_chunking(
    db: Session,
    document_id: UUID,
    initiated_by: UUID,
    *,
    settings: IngestionSettings | None = None,
) -> IngestionJob:
    """Clean and chunk one extracted document and record the outcome."""
    settings = settings or get_ingestion_settings()

    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise ValueError(f"KnowledgeDocument {document_id} does not exist.")
    source_version = db.get(SourceVersion, document.source_version_id)
    source = db.get(KnowledgeSource, source_version.source_id) if source_version else None

    base_counts: dict[str, Any] = {"stage": STAGE, "document_id": str(document.id)}
    job = IngestionJob(
        source_id=source.id if source else None,
        source_version_id=document.source_version_id,
        knowledge_document_id=document.id,
        status=JobStatus.RUNNING,
        started_at=_now(),
        initiated_by=initiated_by,
        counts=base_counts,
    )
    db.add(job)
    document.processing_status = DocumentStatus.CHUNKING
    db.commit()

    try:
        if not extraction_output_path(document.id, settings).is_file():
            raise ExtractionError(
                ExtractionErrorCode.NO_EXTRACTION_OUTPUT,
                "No extracted text found for this document; run extraction first.",
            )
        result = load_extraction_result(document.id, settings)

        mode = mode_for_source_type(source.source_type if source else None)
        chunking = chunk_document(
            result,
            mode,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
            header_footer_min_ratio=settings.header_footer_min_ratio,
        )
        if not chunking.chunks:
            raise ExtractionError(
                ExtractionErrorCode.NO_CHUNKS_PRODUCED,
                "No text was left to chunk after cleaning.",
            )

        # One transaction: old chunks out, new chunks in. If anything fails
        # before commit, the database keeps the previous chunks untouched.
        db.execute(delete(DocumentChunk).where(DocumentChunk.knowledge_document_id == document.id))
        db.add_all(build_chunk_rows(document, source, result, chunking.chunks))

        document.processing_status = DocumentStatus.CHUNKED
        job.status = JobStatus.COMPLETED
        job.counts = {**base_counts, **chunking.summary()}
        logger.info("Chunked document %s into %s chunks", document.id, len(chunking.chunks))

    except ExtractionError as exc:
        logger.warning("Chunking failed for document %s: %s", document.id, exc)
        db.rollback()
        document.processing_status = DocumentStatus.CHUNKING_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(exc)
        job.counts = {**base_counts, "error": exc.to_dict()}

    except Exception as exc:
        logger.exception("Unexpected error chunking document %s", document.id)
        db.rollback()
        error = ExtractionError(
            ExtractionErrorCode.UNEXPECTED_ERROR,
            f"Unexpected {type(exc).__name__} during chunking.",
        )
        document.processing_status = DocumentStatus.CHUNKING_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(error)
        job.counts = {**base_counts, "error": error.to_dict()}

    job.finished_at = _now()
    db.commit()
    return job
