"""Keyword / lexical search over indexed legal chunks.

Uses a lightweight BM25 ranking over tokenized chunk text. No external
dependencies are required so unit tests can run without Postgres or Qdrant.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from app.rag.ranking import hit_from_indexed
from app.rag.types import IndexedChunk, SearchHit


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization suitable for legal keyword search."""
    return _TOKEN_RE.findall(text.lower())


class KeywordSearcher:
    """In-memory BM25 keyword searcher."""

    CHANNEL = "keyword"

    def __init__(
        self,
        chunks: Sequence[IndexedChunk] | None = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._chunks: list[IndexedChunk] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_freqs: list[Counter] = []
        self._df: Counter = Counter()
        self._avgdl = 0.0
        if chunks:
            self.index(chunks)

    def index(self, chunks: Sequence[IndexedChunk]) -> None:
        """Replace the searchable corpus."""
        self._chunks = list(chunks)
        self._doc_tokens = [tokenize(chunk.text) for chunk in self._chunks]
        self._doc_freqs = [Counter(tokens) for tokens in self._doc_tokens]
        self._df = Counter()
        for freqs in self._doc_freqs:
            for term in freqs:
                self._df[term] += 1
        total_len = sum(len(tokens) for tokens in self._doc_tokens)
        self._avgdl = (total_len / len(self._doc_tokens)) if self._doc_tokens else 0.0

    def search(self, query: str, *, top_k: int = 10) -> list[SearchHit]:
        """Return BM25-ranked hits for ``query``."""
        if not self._chunks or top_k < 1:
            return []

        query_terms = list(dict.fromkeys(tokenize(query)))
        if not query_terms:
            return []

        n_docs = len(self._chunks)
        scores: list[tuple[float, int]] = []

        for doc_index, freqs in enumerate(self._doc_freqs):
            score = 0.0
            doc_len = len(self._doc_tokens[doc_index])
            for term in query_terms:
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue
                df = self._df[term]
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + self.k1 * (1 - self.b + self.b * doc_len / (self._avgdl or 1.0))
                score += idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((score, doc_index))

        scores.sort(key=lambda item: (-item[0], str(self._chunks[item[1]].chunk_id)))
        hits: list[SearchHit] = []
        for rank, (score, doc_index) in enumerate(scores[:top_k], start=1):
            chunk = self._chunks[doc_index]
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
