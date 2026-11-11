"""Hybrid legal retriever: vector + keyword → RRF → dedupe → filters → sources.

Pipeline
--------
1. Restrict the indexed corpus with authorization and metadata filters so
   disallowed chunks never compete for top-k slots.
2. Run semantic (vector) and keyword (BM25) searches independently.
3. Fuse rankings with Reciprocal Rank Fusion (see ``app.rag.ranking``).
4. Deduplicate by ``chunk_id``, keeping the highest fused score.
5. Confirm every result includes source provenance (id/title + location/URL).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.rag.filters import filter_indexed_corpus
from app.rag.keyword_search import KeywordSearcher
from app.rag.ranking import deduplicate_chunks, reciprocal_rank_fusion
from app.rag.sources import require_source_info
from app.rag.types import (
    AccessContext,
    IndexedChunk,
    MetadataFilters,
    RetrievedChunk,
)
from app.rag.vector_search import InMemoryVectorSearcher, VectorSearcher


class HybridRetriever:
    """Retrieve legal chunks using hybrid vector + keyword search."""

    def __init__(
        self,
        chunks: Sequence[IndexedChunk] | None = None,
        *,
        vector_searcher: VectorSearcher | None = None,
        keyword_searcher: KeywordSearcher | None = None,
        rrf_k: int = 60,
        candidate_multiplier: int = 3,
    ) -> None:
        self.rrf_k = rrf_k
        self.candidate_multiplier = max(1, candidate_multiplier)
        self._corpus: list[IndexedChunk] = list(chunks or [])
        self.vector_searcher = vector_searcher or InMemoryVectorSearcher()
        self.keyword_searcher = keyword_searcher or KeywordSearcher()
        if self._corpus:
            self.index(self._corpus)

    def index(self, chunks: Sequence[IndexedChunk]) -> None:
        """Replace the underlying corpus for both channels."""
        self._corpus = list(chunks)
        # Backends are re-indexed per retrieve call after auth/metadata filtering.

    def retrieve(
        self,
        query: str,
        *,
        access: AccessContext,
        filters: MetadataFilters | None = None,
        top_k: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[RetrievedChunk]:
        """Run hybrid retrieval for ``query`` under the caller's access context."""
        if top_k < 1:
            return []

        allowed = filter_indexed_corpus(self._corpus, access=access, filters=filters)
        if not allowed:
            return []

        self.vector_searcher.index(allowed)
        self.keyword_searcher.index(allowed)

        candidate_k = top_k * self.candidate_multiplier
        vector_hits = self.vector_searcher.search(
            query,
            top_k=candidate_k,
            query_embedding=query_embedding,
        )
        keyword_hits = self.keyword_searcher.search(query, top_k=candidate_k)

        fused = reciprocal_rank_fusion(
            [vector_hits, keyword_hits],
            k=self.rrf_k,
        )
        deduped = deduplicate_chunks(fused)

        results: list[RetrievedChunk] = []
        for chunk in deduped[:top_k]:
            require_source_info(chunk)
            results.append(chunk)
        return results
