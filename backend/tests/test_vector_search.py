"""Acceptance: semantic/vector search returns relevant results."""

from __future__ import annotations

import pytest

from tests.conftest import make_chunk

from app.rag.vector_search import InMemoryVectorSearcher, cosine_similarity


def test_cosine_similarity_identical_and_orthogonal():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_similarity_dimension_mismatch():
    with pytest.raises(ValueError, match="dimensions"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_vector_search_ranks_semantically_related_chunk_first(embed_fn):
    chunks = [
        make_chunk(
            text="Landlord tenant lease rent arrears procedure.",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Compensation for loss or damage caused by breach of contract.",
            embed_fn=embed_fn,
        ),
        make_chunk(
            text="Constitutional protection of personal liberty under article.",
            embed_fn=embed_fn,
        ),
    ]
    searcher = InMemoryVectorSearcher(chunks, embed_fn=embed_fn)
    hits = searcher.search("contract breach damages remedy", top_k=3)

    assert hits
    assert hits[0].channel == "vector"
    assert hits[0].rank == 1
    assert "breach of contract" in hits[0].text.lower()
    assert hits[0].score > 0
    if len(hits) > 1:
        assert hits[0].score >= hits[1].score


def test_vector_search_accepts_explicit_query_embedding(embed_fn):
    chunks = [
        make_chunk(text="Negligence tort duty of care and damages.", embed_fn=embed_fn),
        make_chunk(text="Lease landlord tenant eviction notice.", embed_fn=embed_fn),
    ]
    searcher = InMemoryVectorSearcher(chunks, embed_fn=embed_fn)
    query_embedding = embed_fn("negligence tort damages")
    hits = searcher.search("ignored text", top_k=1, query_embedding=query_embedding)
    assert len(hits) == 1
    assert "negligence" in hits[0].text.lower()


def test_vector_search_requires_embeddings_or_embed_fn():
    chunk = make_chunk(text="Contract text")
    chunk.embedding = None
    searcher = InMemoryVectorSearcher()
    with pytest.raises(ValueError, match="embed_fn"):
        searcher.index([chunk])


def test_vector_search_empty_corpus(embed_fn):
    searcher = InMemoryVectorSearcher([], embed_fn=embed_fn)
    assert searcher.search("contract") == []
