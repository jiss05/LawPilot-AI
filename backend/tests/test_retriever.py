"""End-to-end hybrid retrieval covering all acceptance criteria."""

from __future__ import annotations

from uuid import uuid4

from tests.conftest import make_chunk

from app.rag.retriever import HybridRetriever
from app.rag.sources import source_payload
from app.rag.types import (
    VISIBILITY_PRIVATE,
    AccessContext,
    MetadataFilters,
)
from app.rag.vector_search import InMemoryVectorSearcher


def test_hybrid_retrieve_returns_relevant_contract_chunks(
    sample_corpus, access_matter, embed_fn
):
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "breach of contract damages compensation",
        access=access_matter,
        top_k=5,
    )

    assert results
    assert any("breach of contract" in r.text.lower() for r in results)
    # Scores are non-increasing after RRF + dedupe.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_combines_channels_when_both_match(embed_fn, access_public):
    chunks = [
        make_chunk(
            text="Compensation for loss or damage caused by breach of contract.",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Unrelated bail hearing procedure under criminal law.",
            embed_fn=embed_fn,
        ),
    ]
    retriever = HybridRetriever(
        chunks,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "breach of contract damages",
        access=access_public,
        top_k=2,
    )
    assert results[0].channels  # at least one channel
    # Top hit should be the contract chunk and ideally appear in both channels.
    assert "breach of contract" in results[0].text.lower()
    assert set(results[0].channels) == {"keyword", "vector"}


def test_duplicates_collapsed_to_best_ranked(embed_fn, access_public):
    shared_id = uuid4()
    # Same chunk_id indexed once; fusion itself collapses channel duplicates.
    chunk = make_chunk(
        text="Statute text on breach of contract and damages.",
        chunk_id=shared_id,
        embed_fn=embed_fn,
    )
    retriever = HybridRetriever(
        [chunk],
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "breach of contract damages",
        access=access_public,
        top_k=5,
    )
    assert len(results) == 1
    assert results[0].chunk_id == shared_id


def test_metadata_filters_exclude_other_jurisdictions(
    sample_corpus, access_public, embed_fn
):
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "contract damages",
        access=access_public,
        filters=MetadataFilters(jurisdictions=frozenset({"India"})),
        top_k=10,
    )
    assert results
    assert all(r.source.jurisdiction == "India" for r in results)
    assert all("California" not in r.text for r in results)


def test_authorization_hides_private_and_inactive(
    sample_corpus, access_public, embed_fn
):
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "breach of contract",
        access=access_public,
        top_k=20,
    )
    texts = [r.text for r in results]
    assert texts
    joined = "\n".join(texts)
    assert "Private draft" not in joined
    assert "Internal memo" not in joined
    assert "Superseded" not in joined
    assert "Unprocessed" not in joined
    assert "Matter-specific" not in joined
    assert "Someone else's private" not in joined


def test_matter_member_sees_matter_work_product(
    sample_corpus, access_matter, embed_fn
):
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "contract damages calculation",
        access=access_matter,
        top_k=10,
    )
    assert any("Matter-specific" in r.text for r in results)


def test_owner_sees_own_private_draft(sample_corpus, user_id, embed_fn):
    access = AccessContext(user_id=user_id, is_internal=False)
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "breach of contract remedies",
        access=access,
        top_k=20,
    )
    private = [r for r in results if "Private draft notes" in r.text]
    assert len(private) == 1
    assert all("Someone else's private" not in r.text for r in results)


def test_every_result_includes_source_information(
    sample_corpus, access_matter, embed_fn
):
    retriever = HybridRetriever(
        sample_corpus,
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "contract breach damages",
        access=access_matter,
        top_k=5,
    )
    assert results
    for chunk in results:
        payload = source_payload(chunk)
        assert payload["source_id"]
        assert payload["source_title"]
        # document_id / citation / url may be optional, but present for statutes
        assert "document_id" in payload
        assert "citation" in payload
        assert "url" in payload
        assert "page_number" in payload
        assert "section_ref" in payload


def test_retrieve_top_k_zero_or_empty_corpus(access_public, embed_fn):
    retriever = HybridRetriever(
        [],
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    assert retriever.retrieve("contract", access=access_public, top_k=5) == []

    retriever = HybridRetriever(
        [make_chunk(text="contract damages", embed_fn=embed_fn)],
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    assert retriever.retrieve("contract", access=access_public, top_k=0) == []


def test_no_results_when_filters_exclude_everything(embed_fn, access_public):
    retriever = HybridRetriever(
        [make_chunk(text="contract damages", jurisdiction="India", embed_fn=embed_fn)],
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    results = retriever.retrieve(
        "contract",
        access=access_public,
        filters=MetadataFilters(jurisdictions=frozenset({"UK"})),
        top_k=5,
    )
    assert results == []


def test_private_visibility_constant_used(user_id, embed_fn):
    chunk = make_chunk(
        text="secret contract note",
        visibility=VISIBILITY_PRIVATE,
        uploaded_by=user_id,
        embed_fn=embed_fn,
    )
    retriever = HybridRetriever(
        [chunk],
        vector_searcher=InMemoryVectorSearcher(embed_fn=embed_fn),
    )
    allowed = retriever.retrieve(
        "contract",
        access=AccessContext(user_id=user_id),
        top_k=1,
    )
    denied = retriever.retrieve(
        "contract",
        access=AccessContext(user_id=uuid4()),
        top_k=1,
    )
    assert len(allowed) == 1
    assert denied == []
