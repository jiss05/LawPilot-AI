"""Source provenance helpers for retrieved chunks."""

from __future__ import annotations

from app.rag.types import RetrievedChunk, SourceInfo


def require_source_info(chunk: RetrievedChunk) -> SourceInfo:
    """Validate that a retrieved chunk carries usable source provenance.

    Raises ``ValueError`` when required identifiers or a title are missing.
    """
    source = chunk.source
    if source.source_id is None:
        raise ValueError(f"Chunk {chunk.chunk_id} is missing source_id")
    if not source.source_title:
        raise ValueError(f"Chunk {chunk.chunk_id} is missing source_title")
    return source


def source_payload(chunk: RetrievedChunk) -> dict:
    """Serialize source fields for agent / API consumers."""
    source = require_source_info(chunk)
    return {
        "source_id": str(source.source_id),
        "source_title": source.source_title,
        "document_id": str(source.document_id) if source.document_id else None,
        "url": source.url,
        "citation": source.citation,
        "page_number": source.page_number,
        "section_ref": source.section_ref,
        "publisher": source.publisher,
        "source_type": source.source_type,
        "jurisdiction": source.jurisdiction,
        "trust_tier": source.trust_tier,
    }


def build_citation(page_number: int | None, section_ref: str | None) -> str | None:
    """Build a human-readable citation/location string when possible."""
    parts: list[str] = []
    if section_ref:
        parts.append(section_ref)
    if page_number is not None:
        parts.append(f"p. {page_number}")
    return ", ".join(parts) if parts else None
