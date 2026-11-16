# Retrieval (`app/rag`)

Jira: *Implement hybrid retrieval* (SCRUM-16). BRD §10.2.

## Two layers

| Layer | Files | Data |
|---|---|---|
| Retrieval **rules** (from `hybrid-search-v1`) | `types.py`, `filters.py`, `ranking.py`, `sources.py`, `retriever.py`, `vector_search.py`, `keyword_search.py` | In-memory: unit tests and experiments |
| Retrieval over the **real stores** (SCRUM-16) | `store_retriever.py`, `../api/research_routes.py` | Qdrant (vectors) + PostgreSQL (full-text, metadata) |

`store_retriever.LegalSearchService` reuses the rules: `filter_search_hits` (authorization), `reciprocal_rank_fusion` and `deduplicate_chunks` (ranking), and `require_source_info` (provenance).

## Flow of one search

```
POST /api/v1/research/search {"query": "...", "top_k": 10, "jurisdictions": ["India"]}
  ├─ vector channel:  embed question ► Qdrant top-N   (visibility + metadata filters inside Qdrant)
  ├─ keyword channel: PostgreSQL full-text top-N      (GIN index; active edition + ready document + filters in SQL)
  ├─ hydrate:         one SQL query: text, page, section, edition, source for every candidate
  ├─ authorize again: filters.filter_search_hits      (defence in depth)
  ├─ fuse:            Reciprocal Rank Fusion, score = Σ 1/(60 + rank)
  ├─ de-duplicate:    by chunk id, then by identical text
  └─ top_k results with source title, URL, edition, citation ("Section 73, p. 17"), pages
```

## Who sees what

| `knowledge_documents.visibility` | CLIENT | LAWYER / JUDGE | ADMIN |
|---|---|---|---|
| `public` (upload default) | yes | yes | yes |
| `internal` | no | yes | yes |
| `private` | only own uploads | only own uploads | yes |

In every case, a document is only returned when its edition is `active` and its `processing_status` is `completed` (set by activation, SCRUM-18).

## Acceptance criteria

| Criterion | Where | Tests |
|---|---|---|
| Semantic and keyword searches return relevant results | `_vector_candidates`, `keyword_candidates` | `tests/integration/test_hybrid_retrieval_db.py` |
| Retrieval rankings are combined correctly | `ranking.reciprocal_rank_fusion` | `tests/test_ranking.py`, integration |
| Duplicate chunks are removed | `deduplicate_chunks`, `deduplicate_by_content` | `test_duplicate_chunks_removed` |
| Metadata and authorization filters are applied | `qdrant_filter`, `_sql_conditions`, `filter_search_hits` | `test_metadata_filters`, `test_internal_…`, `test_private_…`, `test_unactivated_…` |
| Relevant source information is returned | `_hit` → `SourceInfo` + edition/page metadata | `test_source_information_returned`, `test_research_api.py` |

If Qdrant or the embedding model is unavailable, search answers from the keyword channel and reports `"degraded": ["vector"]` (BRD NFR-02).

## Running the database tests

```bash
# from backend/, with Docker Postgres running and migrated (alembic upgrade head)
TEST_DATABASE_URL=postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai pytest tests/integration -v
```
Each test runs in a transaction that is rolled back afterwards.
