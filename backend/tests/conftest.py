"""Shared pytest fixtures for LawPilot retrieval tests."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# Ensure `app` is importable when pytest is run from repo root or backend/.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.rag.sources import build_citation
from app.rag.types import (
    VISIBILITY_INTERNAL,
    VISIBILITY_MATTER,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    AccessContext,
    IndexedChunk,
    SourceInfo,
)


def bag_of_words_embed(text: str, vocab: list[str] | None = None) -> list[float]:
    """Deterministic sparse-style embedding for semantic relevance tests."""
    default_vocab = [
        "contract",
        "breach",
        "damages",
        "negligence",
        "tort",
        "lease",
        "tenant",
        "landlord",
        "constitution",
        "article",
        "bail",
        "criminal",
        "evidence",
        "statute",
        "limitation",
    ]
    terms = vocab or default_vocab
    lowered = text.lower()
    return [float(lowered.count(term)) for term in terms]


@pytest.fixture
def embed_fn():
    return bag_of_words_embed


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def matter_id() -> UUID:
    return uuid4()


@pytest.fixture
def other_user_id() -> UUID:
    return uuid4()


@pytest.fixture
def access_public() -> AccessContext:
    """Unauthenticated-style caller who does not own any private corpus rows."""
    return AccessContext(user_id=uuid4(), is_internal=False)


@pytest.fixture
def access_internal(user_id: UUID) -> AccessContext:
    return AccessContext(user_id=user_id, is_internal=True, roles=frozenset({"lawyer"}))


@pytest.fixture
def access_matter(user_id: UUID, matter_id: UUID) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        matter_ids=frozenset({matter_id}),
        is_internal=True,
        roles=frozenset({"lawyer"}),
    )


@pytest.fixture
def access_admin(user_id: UUID) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        is_internal=True,
        roles=frozenset({"admin"}),
    )


def make_chunk(
    *,
    text: str,
    title: str = "Indian Contract Act",
    visibility: str = VISIBILITY_PUBLIC,
    matter_id: UUID | None = None,
    version_status: str = "active",
    processing_status: str = "completed",
    uploaded_by: UUID | None = None,
    jurisdiction: str = "India",
    trust_tier: str = "primary",
    source_type: str = "statute",
    url: str | None = "https://example.org/contract-act",
    page_number: int | None = 12,
    section_ref: str | None = "Section 73",
    metadata: dict | None = None,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    source_id: UUID | None = None,
    embed_fn=bag_of_words_embed,
) -> IndexedChunk:
    source_id = source_id or uuid4()
    document_id = document_id or uuid4()
    citation = build_citation(page_number, section_ref)
    source = SourceInfo(
        source_id=source_id,
        source_title=title,
        document_id=document_id,
        url=url,
        citation=citation,
        page_number=page_number,
        section_ref=section_ref,
        publisher="Government of India",
        source_type=source_type,
        jurisdiction=jurisdiction,
        trust_tier=trust_tier,
    )
    return IndexedChunk(
        chunk_id=chunk_id or uuid4(),
        text=text,
        source=source,
        embedding=embed_fn(text),
        visibility=visibility,
        matter_id=matter_id,
        version_status=version_status,
        processing_status=processing_status,
        uploaded_by=uploaded_by,
        jurisdiction=jurisdiction,
        trust_tier=trust_tier,
        source_type=source_type,
        metadata=metadata or {},
    )


@pytest.fixture
def sample_corpus(user_id, other_user_id, matter_id, embed_fn) -> list[IndexedChunk]:
    return [
        make_chunk(
            text="Compensation for loss or damage caused by breach of contract.",
            title="Indian Contract Act",
            section_ref="Section 73",
            page_number=40,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Negligence in tort requires duty of care, breach, and damages.",
            title="Law of Torts",
            source_type="treatise",
            trust_tier="secondary",
            section_ref="Chapter 4",
            page_number=88,
            url="https://example.org/torts",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="A landlord may terminate a lease for unpaid rent by a tenant.",
            title="Transfer of Property Act",
            section_ref="Section 111",
            page_number=15,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Internal memo on contract breach litigation strategy.",
            title="Firm Litigation Memo",
            visibility=VISIBILITY_INTERNAL,
            source_type="memo",
            trust_tier="internal",
            url=None,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Matter-specific contract damages calculation for client dispute.",
            title="Matter Work Product",
            visibility=VISIBILITY_MATTER,
            matter_id=matter_id,
            source_type="work_product",
            trust_tier="matter",
            url=None,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Private draft notes about breach of contract remedies.",
            title="Private Draft",
            visibility=VISIBILITY_PRIVATE,
            uploaded_by=user_id,
            source_type="draft",
            trust_tier="private",
            url=None,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Someone else's private notes on negligence claims.",
            title="Other Private Draft",
            visibility=VISIBILITY_PRIVATE,
            uploaded_by=other_user_id,
            source_type="draft",
            trust_tier="private",
            url=None,
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Superseded statute text about breach of contract damages.",
            title="Old Contract Act",
            version_status="superseded",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Unprocessed upload mentioning contract breach remedies.",
            title="Pending Upload",
            processing_status="pending",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Article 21 of the Constitution protects life and personal liberty.",
            title="Constitution of India",
            jurisdiction="India",
            source_type="constitution",
            section_ref="Article 21",
            page_number=1,
            url="https://example.org/constitution",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="California civil code provisions on contract damages.",
            title="California Civil Code",
            jurisdiction="USA-CA",
            section_ref="§ 3300",
            page_number=2,
            url="https://example.org/ca-civil",
            embed_fn=embed_fn,
        ),
    ]
