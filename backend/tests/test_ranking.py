"""Acceptance: combine rankings (RRF) and deduplicate keeping best rank."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.rag.ranking import deduplicate_chunks, reciprocal_rank_fusion
from app.rag.types import RetrievedChunk, SearchHit, SourceInfo


def _source(title: str = "Act") -> SourceInfo:
    return SourceInfo(source_id=uuid4(), source_title=title, document_id=uuid4())


def _hit(chunk_id, *, rank: int, channel: str, score: float = 1.0, text: str = "text") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        score=score,
        rank=rank,
        channel=channel,
        text=text,
        source=_source(),
    )


def test_rrf_prefers_items_ranked_high_in_both_channels():
    a, b, c = uuid4(), uuid4(), uuid4()
    vector = [
        _hit(a, rank=1, channel="vector"),
        _hit(b, rank=2, channel="vector"),
        _hit(c, rank=3, channel="vector"),
    ]
    keyword = [
        _hit(b, rank=1, channel="keyword"),
        _hit(a, rank=2, channel="keyword"),
        _hit(c, rank=3, channel="keyword"),
    ]

    fused = reciprocal_rank_fusion([vector, keyword], k=60)
    scores = {item.chunk_id: item.score for item in fused}
    # a and b each appear once at rank 1 and once at rank 2 → identical RRF scores
    assert scores[a] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[a] == pytest.approx(scores[b])
    assert scores[a] > scores[c]
    assert fused[0].chunk_id in {a, b}
    assert fused[-1].chunk_id == c
    both = next(item for item in fused if item.chunk_id == a)
    assert set(both.channels) == {"keyword", "vector"}


def test_rrf_single_channel_preserves_order():
    ids = [uuid4() for _ in range(3)]
    vector = [_hit(chunk_id, rank=i, channel="vector") for i, chunk_id in enumerate(ids, start=1)]
    fused = reciprocal_rank_fusion([vector], k=60)
    assert [item.chunk_id for item in fused] == ids


def test_rrf_rejects_invalid_k():
    with pytest.raises(ValueError, match="k must be"):
        reciprocal_rank_fusion([[]], k=0)


def test_deduplicate_keeps_highest_score():
    chunk_id = uuid4()
    source = _source("Contract Act")
    chunks = [
        RetrievedChunk(chunk_id=chunk_id, text="low", score=0.1, source=source, channels=("vector",)),
        RetrievedChunk(
            chunk_id=chunk_id,
            text="high",
            score=0.9,
            source=source,
            channels=("keyword",),
        ),
        RetrievedChunk(
            chunk_id=uuid4(),
            text="other",
            score=0.5,
            source=_source(),
            channels=("vector",),
        ),
    ]
    deduped = deduplicate_chunks(chunks)
    assert len(deduped) == 2
    kept = next(item for item in deduped if item.chunk_id == chunk_id)
    assert kept.score == 0.9
    assert kept.text == "high"
    assert deduped[0].score >= deduped[1].score


def test_deduplicate_empty_and_unique():
    assert deduplicate_chunks([]) == []
    only = RetrievedChunk(
        chunk_id=uuid4(),
        text="only",
        score=1.0,
        source=_source(),
        channels=("vector",),
    )
    assert deduplicate_chunks([only]) == [only]


def test_rrf_merges_duplicate_chunk_across_lists():
    chunk_id = uuid4()
    vector = [_hit(chunk_id, rank=1, channel="vector", text="from vector")]
    keyword = [_hit(chunk_id, rank=1, channel="keyword", text="from keyword")]
    fused = reciprocal_rank_fusion([vector, keyword], k=60)
    assert len(fused) == 1
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 61)
    assert set(fused[0].channels) == {"keyword", "vector"}
