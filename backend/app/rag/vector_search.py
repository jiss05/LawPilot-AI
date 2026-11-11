"""Semantic / vector search over indexed legal chunks.

Provides an in-memory cosine-similarity store for tests and local development.
A Qdrant-backed adapter can implement the same ``VectorSearcher`` protocol
without changing the hybrid retriever.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Protocol

from app.rag.ranking import hit_from_indexed
from app.rag.types import IndexedChunk, SearchHit


EmbedFn = Callable[[str], list[float]]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; returns 0.0 for zero-length vectors."""
    if len(a) != len(b):
        raise ValueError("Embedding dimensions must match")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class VectorSearcher(Protocol):
    """Protocol for semantic search backends."""

    CHANNEL: str

    def index(self, chunks: Sequence[IndexedChunk]) -> None: ...

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[SearchHit]: ...


class InMemoryVectorSearcher:
    """Brute-force cosine search over precomputed (or on-index) embeddings."""

    CHANNEL = "vector"

    def __init__(
        self,
        chunks: Sequence[IndexedChunk] | None = None,
        *,
        embed_fn: EmbedFn | None = None,
    ) -> None:
        self.embed_fn = embed_fn
        self._chunks: list[IndexedChunk] = []
        if chunks:
            self.index(chunks)

    def index(self, chunks: Sequence[IndexedChunk]) -> None:
        """Replace the searchable corpus; embed texts when embeddings missing."""
        indexed: list[IndexedChunk] = []
        for chunk in chunks:
            embedding = chunk.embedding
            if embedding is None:
                if self.embed_fn is None:
                    raise ValueError(
                        f"Chunk {chunk.chunk_id} has no embedding and no embed_fn was provided"
                    )
                embedding = self.embed_fn(chunk.text)
            indexed.append(
                IndexedChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    source=chunk.source,
                    embedding=list(embedding),
                    visibility=chunk.visibility,
                    matter_id=chunk.matter_id,
                    version_status=chunk.version_status,
                    processing_status=chunk.processing_status,
                    uploaded_by=chunk.uploaded_by,
                    jurisdiction=chunk.jurisdiction,
                    trust_tier=chunk.trust_tier,
                    source_type=chunk.source_type,
                    metadata=dict(chunk.metadata),
                )
            )
        self._chunks = indexed

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[SearchHit]:
        """Return cosine-ranked vector hits for ``query``."""
        if not self._chunks or top_k < 1:
            return []

        if query_embedding is None:
            if self.embed_fn is None:
                raise ValueError("query_embedding or embed_fn is required for vector search")
            query_embedding = self.embed_fn(query)

        scored: list[tuple[float, IndexedChunk]] = []
        for chunk in self._chunks:
            assert chunk.embedding is not None
            score = cosine_similarity(query_embedding, chunk.embedding)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: (-item[0], str(item[1].chunk_id)))
        hits: list[SearchHit] = []
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1):
            hits.append(
                hit_from_indexed(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=score,
                    rank=rank,
                    channel=self.CHANNEL,
                    source=chunk.source,
                    visibility=chunk.visibility,
                    matter_id=chunk.matter_id,
                    version_status=chunk.version_status,
                    processing_status=chunk.processing_status,
                    uploaded_by=chunk.uploaded_by,
                    jurisdiction=chunk.jurisdiction,
                    trust_tier=chunk.trust_tier,
                    source_type=chunk.source_type,
                    metadata=chunk.metadata,
                )
            )
        return hits
