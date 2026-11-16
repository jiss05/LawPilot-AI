# Ingestion: extraction, OCR, cleaning, chunking and indexing

Jira stories (Sprint 2):
- *Implement document text extraction and OCR*
- *Implement document cleaning and chunking* (SCRUM-14)
- *Implement embeddings and Qdrant indexing* (SCRUM-15)
- *Implement source versioning and ingestion monitoring* (SCRUM-18)

BRD references: §5.2 ingestion flow, §8.2 `document_chunks`, §10.1 pipeline steps, FR-016 and FR-021.

## Where this fits

```
admin uploads PDF ──► background task (starts automatically)
POST /api/v1/         ├─ extraction: validate ► extract ► OCR if needed ► JSON
knowledge-sources     ├─ chunking:   clean ► detect sections ► chunk ► document_chunks
                      ├─ indexing:   embed ► Qdrant (point id = chunk id) ► verify
                      └─ activation: final checks ► document "completed" ► edition "active" (old edition "superseded")
```

## Files

| File | Responsibility |
|---|---|
| `config.py` | `IngestionSettings`, read from `INGESTION_*` variables in `backend/.env` |
| `errors.py` | `ExtractionError` and its stable error codes (extraction and chunking) |
| `extraction_types.py` | `PageText`, `ExtractionResult`: text kept **page by page** |
| `file_validation.py` | Size, extension, magic bytes, DOCX zip check, SHA-256 |
| `text_quality.py` | Decides whether native text is "insufficient" (too little or garbled) |
| `loaders/*.py` | PDF (PyMuPDF), DOCX, TXT, images (PNG/JPEG/TIFF) |
| `ocr.py` | `OcrEngine` interface and `EasyOcrEngine` |
| `extractor.py` | `DocumentExtractor`: validation, loaders and the OCR decision |
| `storage.py` | Safe storage paths; saves and loads `<document_id>.extracted.json` |
| `pipeline.py` | `run_extraction()`: updates `knowledge_documents` and `ingestion_jobs` |
| `chunking/cleaner.py` | Character normalisation, header/footer and page-number removal, de-hyphenation, paragraphs |
| `chunking/structure.py` | Labels each paragraph: Chapter, Section 73, (1), (a), Explanation, Para 12 |
| `chunking/chunker.py` | Groups blocks into legal units and makes chunks with page and section references |
| `chunking/tokens.py` | Approximate token count (characters / 4) |
| `chunk_pipeline.py` | `run_chunking()`: writes `document_chunks`, records an `ingestion_jobs` row |
| `embeddings.py` | `EmbeddingProvider`: sentence-transformers (default), Ollama, or hashing (tests/offline) |
| `vector_store.py` | `QdrantVectorStore`: collection setup, write/replace points, count, retrieve, search, health |
| `index_pipeline.py` | `run_indexing()`: embeds chunks, writes Qdrant, verifies ids and payloads, records the job |
| `activation.py` | `run_activation()` (last stage), `activate_version()`, `withdraw_version()`: edition management |
| `tasks.py` | `process_uploaded_document()`: runs extraction → chunking → indexing → activation after an upload |
| `cli.py` | `extract <file>`, `chunk <file>`, `run <document_id>` |

## How each acceptance criterion is met

**Text extraction and OCR**

| Acceptance criterion | Where |
|---|---|
| Text extracted from supported formats (PDF, DOCX, TXT, PNG, JPEG, TIFF) | `loaders/*`, `extractor.py` |
| OCR when normal extraction is insufficient | `text_quality.assess_text` and `DocumentExtractor._ocr_pdf_page` |
| Page references preserved where available | `PageText.page_number` and `ExtractionResult.page_numbers_reliable` |
| Extraction failures recorded | `pipeline.run_extraction`: `ingestion_jobs.status`, `error_summary`, `counts["error"]` |
| Empty or corrupted documents identified | `file_validation.py`, loaders, `_ensure_not_empty`, which set the `empty` or `corrupted` status |

**Cleaning and chunking**

| Acceptance criterion | Where |
|---|---|
| Extracted text is cleaned and normalised | `chunking/cleaner.py` (tests: `test_chunking_cleaner.py`) |
| Legal sections and paragraphs are preserved | `chunking/structure.py` labels units; `chunker._build_units` keeps sub-sections, clauses and explanations inside their section; statute sections are never merged |
| Documents are divided into meaningful chunks | `chunking/chunker.py`: one chunk per section or paragraph; long ones split at block, then sentence, then word boundaries, with overlap |
| Each chunk keeps its source and page references | `document_chunks.knowledge_document_id`, `source_version_id`, `page_number` and `metadata.page_start` / `page_end` / `source_id` / `source_title` |
| Chunk metadata is stored correctly | `chunk_pipeline.build_chunk_rows` (tests: `test_chunk_pipeline.py`) |

**Embeddings and Qdrant indexing (SCRUM-15)**

| Acceptance criterion | Where |
|---|---|
| Embeddings are generated successfully | `embeddings.py`; every batch checked by `validate_vectors` (count, size, NaN, zero) |
| Vectors are stored in Qdrant | `vector_store.replace_document_points` (collection `legal_chunks_v1`, cosine distance) |
| Chunk identifiers stay consistent across databases | Qdrant point id = `document_chunks.id`; `verify_index` checks every id after writing |
| Metadata is associated with the correct vectors | `index_pipeline.build_payload`; `verify_index` compares chunk id, document id and a text hash |
| Indexing failures are identified | Codes `NO_CHUNKS_TO_INDEX`, `EMBEDDING_FAILED`, `VECTOR_STORE_UNAVAILABLE`, `VECTOR_DIMENSION_MISMATCH`, `INDEX_VERIFICATION_FAILED`, which set the document to `indexing_failed` |

**Source versioning and ingestion monitoring (SCRUM-18)**

| Acceptance criterion | Where |
|---|---|
| Source versions are maintained | `POST /api/v1/knowledge-sources/{id}/versions` (new edition), `GET .../versions` (history), `activation.activate_version` (one active edition per source) |
| Previous versions are preserved | Superseding or withdrawing only changes `source_versions.status`; files, chunks and vectors are kept, and `supersedes_version_id` links the chain. Roll back with `POST .../versions/{vid}/activate` |
| Ingestion status is recorded | One `ingestion_jobs` row per stage (`text_extraction`, `chunking`, `indexing`, `activation`) plus `knowledge_documents.processing_status` |
| Processing failures are visible | `GET /api/v1/admin/ingestion-jobs?status=failed`, `GET /api/v1/admin/ingestion-jobs/summary` (failures by error code, failed documents), `GET /api/v1/admin/documents/{id}/status` |
| Administrative operations are traceable | `audit_events` rows (`app/services/audit_service.py`), with actor, target, reason and `X-Request-ID`. Read through `GET /api/v1/admin/audit-events` |

### Admin API (ADMIN role only)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/knowledge-sources/{source_id}/versions` | Upload a new edition (multipart: `file`, `version_label`, `published_at`, `visibility`) |
| GET | `/api/v1/knowledge-sources/{source_id}/versions` | Edition history with status, documents and chunk counts |
| POST | `/api/v1/knowledge-sources/{source_id}/versions/{version_id}/activate` | Make an edition the searchable one (roll back), with `{"reason": "..."}` |
| POST | `/api/v1/knowledge-sources/{source_id}/versions/{version_id}/withdraw` | Remove an edition from search, with `{"reason": "..."}` |
| GET | `/api/v1/admin/ingestion-jobs` | Job history; filters `status`, `stage`, `document_id`, `source_id` |
| POST | `/api/v1/admin/ingestion-jobs` | Start or retry processing: `{"document_id": "..."}` |
| GET | `/api/v1/admin/ingestion-jobs/summary` | Dashboard numbers, failed documents, Qdrant health |
| GET | `/api/v1/admin/documents/{document_id}/status` | One document's timeline, chunk and vector counts, `searchable` |
| GET | `/api/v1/admin/audit-events` | Audit trail; filters `action`, `target_id`, `actor_user_id` |

## What a chunk row looks like (`document_chunks`)

| Column | Example | Meaning |
|---|---|---|
| `id` | `uuid5(document_id, "chunk-2")` | Stable: re-chunking gives the same id |
| `knowledge_document_id` | the uploaded file | New in migration `c4d8e2f1a7b3` |
| `source_version_id` | the edition | |
| `chunk_index` | `2` | Order inside the file |
| `text` | `73. Compensation for loss ...` | Cleaned text |
| `page_number` | `2` | First page of the chunk |
| `section_ref` | `Section 73` / `Para 12` / `Paras 4-6` | Legal unit |
| `token_count` | `384` | Approximate (chars / 4) |
| `metadata` | `{"page_end": 3, "part": 1, "parts": 3, "heading_path": ["CHAPTER VI", ...], "extraction_methods": ["native"], ...}` | Everything else |

## Status values

`knowledge_documents.processing_status`:
`pending` (upload) → `extracting` → `extracted` → `chunking` → `chunked` → `indexing` → `indexed` → `completed`,
or `empty` / `corrupted` / `extraction_failed` / `chunking_failed` / `indexing_failed` / `activation_failed`.

`source_versions.status`: `pending` → `active` (after activation) → `superseded` (newer edition activated) or `withdrawn` (by an admin); `failed` if the new edition's processing failed.

`ingestion_jobs`: one row per stage (`counts.stage` = `text_extraction`, `chunking`, `indexing` or `activation`), `status` `running` → `completed` or `failed`, linked by `knowledge_document_id`.

Search (`app/rag`) only returns `completed` documents whose edition is `active`.

## Settings (`backend/.env`, all optional)

```
INGESTION_STORAGE_DIR=            # default: backend/legal_documents (shared by upload and extraction)
INGESTION_EXTRACTED_DIR=          # default: backend/storage/extracted
INGESTION_MAX_FILE_SIZE_MB=50
INGESTION_MAX_PAGES=2000
INGESTION_MIN_NATIVE_CHARS_PER_PAGE=50
INGESTION_MIN_TEXT_QUALITY_RATIO=0.6
INGESTION_OCR_ENABLED=true
INGESTION_OCR_LANGUAGES=["en"]
INGESTION_OCR_GPU=false
INGESTION_OCR_DPI=300
INGESTION_OCR_LOW_CONFIDENCE_WARNING=0.5
INGESTION_CHUNK_MAX_TOKENS=400
INGESTION_CHUNK_OVERLAP_TOKENS=50
INGESTION_CHUNK_MIN_TOKENS=40
INGESTION_HEADER_FOOTER_MIN_RATIO=0.5
INGESTION_EMBEDDING_PROVIDER=sentence-transformers   # or ollama, or hashing (tests/offline)
INGESTION_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5      # 384 dimensions; downloaded on first use
INGESTION_QDRANT_COLLECTION=legal_chunks_v1          # new name when the embedding model changes
QDRANT_URL=http://localhost:6333                     # or :memory: / path:<folder> for embedded Qdrant
```

## Tests

```
pytest tests/ingestion                     # fast; fake OCR engine and fake DB session
$env:RUN_OCR_TESTS="1"; pytest tests/ingestion/test_ingestion_real_ocr.py -s   # real EasyOCR
```

The full flow (upload through the API → background extraction → chunking → rows in PostgreSQL) was also run against a real PostgreSQL 16 database during development, including `alembic upgrade` / `downgrade` of migration `c4d8e2f1a7b3`.
