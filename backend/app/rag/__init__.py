"""Retrieval-augmented generation helpers for LawPilot AI."""

from app.rag.filters import (
    apply_access_filters,
    apply_metadata_filters,
    filter_indexed_corpus,
    filter_search_hits,
    is_authorized,
)
from app.rag.keyword_search import KeywordSearcher
from app.rag.ranking import (
    DEFAULT_RRF_K,
    deduplicate_chunks,
    reciprocal_rank_fusion,
)
from app.rag.retriever import HybridRetriever
from app.rag.sources import build_citation, require_source_info, source_payload
from app.rag.types import (
    AccessContext,
    IndexedChunk,
    MetadataFilters,
    RetrievedChunk,
    SearchHit,
    SourceInfo,
)
from app.rag.vector_search import InMemoryVectorSearcher, cosine_similarity

__all__ = [
    "AccessContext",
    "DEFAULT_RRF_K",
    "HybridRetriever",
    "IndexedChunk",
    "InMemoryVectorSearcher",
    "KeywordSearcher",
    "MetadataFilters",
    "RetrievedChunk",
    "SearchHit",
    "SourceInfo",
    "apply_access_filters",
    "apply_metadata_filters",
    "build_citation",
    "cosine_similarity",
    "deduplicate_chunks",
    "filter_indexed_corpus",
    "filter_search_hits",
    "is_authorized",
    "reciprocal_rank_fusion",
    "require_source_info",
    "source_payload",
]
