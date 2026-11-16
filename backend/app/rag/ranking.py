"""Ranking fusion and chunk deduplication for hybrid retrieval.

Ranking strategy — Reciprocal Rank Fusion (RRF)
-----------------------------------------------
Vector and keyword channels produce independent ranked lists. We fuse them with
classic RRF (Cormack et al.):

    fused_score(d) = Σ_channel  1 / (k + rank_channel(d))

where ``rank`` is 1-based and ``k`` defaults to 60. RRF is chosen because it:

* does not require calibrated/cross-channel score normalization
* rewards items that appear near the top of either (or both) lists
* is the standard hybrid default when no project-specific fusion is documented

After fusion, hits sharing the same ``chunk_id`` are collapsed, keeping the
single best (highest) fused score.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from app.rag.types import RetrievedChunk, SearchHit, SourceInfo


DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[SearchHit]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    """Fuse one or more channel rankings with Reciprocal Rank Fusion.

    Each hit contributes ``1 / (k + rank)`` using the hit's 1-based ``rank``.
    Duplicate ``chunk_id`` values across or within lists accumulate score and
    are returned once (best provenance retained from the highest contribution
    order: first-seen hit supplies text/source/metadata; channels are merged).
    """
    if k < 1:
        raise ValueError("RRF constant k must be >= 1")

    scores: dict = defaultdict(float)
    channels: dict = defaultdict(set)
    payloads: dict = {}

    for ranked in ranked_lists:
        for hit in ranked:
            contribution = 1.0 / (k + hit.rank)
            scores[hit.chunk_id] += contribution
            channels[hit.chunk_id].add(hit.channel)
            if hit.chunk_id not in payloads:
                payloads[hit.chunk_id] = hit

    fused = [
        RetrievedChunk(
            chunk_id=chunk_id,
            text=payloads[chunk_id].text,
            score=score,
            source=payloads[chunk_id].source,
            channels=tuple(sorted(channels[chunk_id])),
            metadata=dict(payloads[chunk_id].metadata),
        )
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, str(item.chunk_id)))
    return fused


def deduplicate_chunks(
    chunks: Iterable[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Remove duplicate chunk_ids, preserving the best-ranked occurrence.

    "Best" means the highest ``score``. Ties keep the first occurrence in the
    input order (stable). Results are returned sorted by descending score.
    """
    best: dict = {}
    order: list = []

    for chunk in chunks:
        existing = best.get(chunk.chunk_id)
        if existing is None:
            best[chunk.chunk_id] = chunk
            order.append(chunk.chunk_id)
            continue
        if chunk.score > existing.score:
            best[chunk.chunk_id] = chunk

    deduped = [best[chunk_id] for chunk_id in order]
    deduped.sort(key=lambda item: (-item.score, str(item.chunk_id)))
    return deduped


def hit_from_indexed(
    *,
    chunk_id,
    text: str,
    score: float,
    rank: int,
    channel: str,
    source: SourceInfo,
    visibility: str,
    matter_id,
    version_status: str,
    processing_status: str,
    uploaded_by,
    jurisdiction: str,
    trust_tier: str,
    source_type: str,
    metadata: dict,
) -> SearchHit:
    """Helper to build a SearchHit with consistent field mapping."""
    return SearchHit(
        chunk_id=chunk_id,
        score=score,
        rank=rank,
        channel=channel,
        text=text,
        source=source,
        visibility=visibility,
        matter_id=matter_id,
        version_status=version_status,
        processing_status=processing_status,
        uploaded_by=uploaded_by,
        jurisdiction=jurisdiction,
        trust_tier=trust_tier,
        source_type=source_type,
        metadata=metadata,
    )
