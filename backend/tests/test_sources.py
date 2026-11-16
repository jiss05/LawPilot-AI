"""Acceptance: every retrieved chunk includes source provenance."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.rag.sources import build_citation, require_source_info, source_payload
from app.rag.types import RetrievedChunk, SourceInfo


def test_build_citation_combinations():
    assert build_citation(12, "Section 73") == "Section 73, p. 12"
    assert build_citation(None, "Article 21") == "Article 21"
    assert build_citation(5, None) == "p. 5"
    assert build_citation(None, None) is None


def test_require_source_info_and_payload():
    source = SourceInfo(
        source_id=uuid4(),
        source_title="Indian Contract Act",
        document_id=uuid4(),
        url="https://example.org/contract-act",
        citation="Section 73, p. 40",
        page_number=40,
        section_ref="Section 73",
        publisher="Government of India",
        source_type="statute",
        jurisdiction="India",
        trust_tier="primary",
    )
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        text="Compensation for breach of contract.",
        score=0.8,
        source=source,
        channels=("vector", "keyword"),
    )
    assert require_source_info(chunk) is source
    payload = source_payload(chunk)
    assert payload["source_id"] == str(source.source_id)
    assert payload["source_title"] == "Indian Contract Act"
    assert payload["document_id"] == str(source.document_id)
    assert payload["url"] == source.url
    assert payload["citation"] == "Section 73, p. 40"
    assert payload["page_number"] == 40
    assert payload["section_ref"] == "Section 73"


def test_missing_source_title_rejected():
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        text="x",
        score=1.0,
        source=SourceInfo(source_id=uuid4(), source_title=""),
        channels=("vector",),
    )
    with pytest.raises(ValueError, match="source_title"):
        require_source_info(chunk)
