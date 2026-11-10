"""Acceptance: keyword search returns relevant results."""

from __future__ import annotations

from tests.conftest import make_chunk

from app.rag.keyword_search import KeywordSearcher, tokenize


def test_tokenize_lowercases_and_splits():
    assert tokenize("Breach-of Contract, 73!") == ["breach", "of", "contract", "73"]


def test_keyword_search_ranks_relevant_chunk_first():
    chunks = [
        make_chunk(text="Rules about landlord and tenant lease disputes."),
        make_chunk(text="Compensation for loss caused by breach of contract."),
        make_chunk(text="Bail procedure under the criminal procedure code."),
    ]
    searcher = KeywordSearcher(chunks)
    hits = searcher.search("breach of contract damages", top_k=3)

    assert hits
    assert hits[0].rank == 1
    assert hits[0].channel == "keyword"
    assert "breach of contract" in hits[0].text.lower()
    assert all(hit.score > 0 for hit in hits)
    if len(hits) > 1:
        assert hits[0].score >= hits[1].score


def test_keyword_search_empty_query_returns_no_hits():
    searcher = KeywordSearcher([make_chunk(text="Contract damages statute.")])
    assert searcher.search("   ") == []
    assert searcher.search("@@@") == []


def test_keyword_search_deduplicates_repeated_query_terms():
    chunks = [
        make_chunk(text="Contract damages clause."),
        make_chunk(text="Other legal text without contract damages."),
    ]
    searcher = KeywordSearcher(chunks)
    single = searcher.search("contract contract damages")
    duplicate = searcher.search("contract damages")
    assert single[0].score == duplicate[0].score


def test_keyword_search_respects_top_k():
    chunks = [
        make_chunk(text=f"contract damages clause number {i}")
        for i in range(5)
    ]
    searcher = KeywordSearcher(chunks)
    hits = searcher.search("contract damages", top_k=2)
    assert len(hits) == 2
    assert [hit.rank for hit in hits] == [1, 2]


def test_keyword_search_on_empty_index():
    assert KeywordSearcher([]).search("contract") == []
