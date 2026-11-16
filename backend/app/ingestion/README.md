# Ingestion: extraction, OCR, cleaning and chunking

Jira stories (Sprint 2):
- *Implement document text extraction and OCR*
- *Implement document cleaning and chunking*

BRD references: §5.2 ingestion flow, §8.2 `document_chunks`, §10.1 pipeline steps, FR-016 and FR-021.

## Where this fits

```
admin uploads PDF ──► background task (starts automatically)                     ──► embed ► Qdrant ► activate
POST /api/v1/         ├─ extraction: validate ► extract ► OCR if needed ► JSON       (later stories)
knowledge-sources     └─ chunking:   clean ► detect sections ► chunk ► document_chunks
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
| `tasks.py` | `process_uploaded_document()`: runs extraction then chunking after an upload |
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
`pending` (upload) → `extracting` → `extracted` → `chunking` → `chunked`,
or `empty` / `corrupted` / `extraction_failed` / `chunking_failed`.

`source_versions.status` stays `pending` until a later activation story sets `active`.

`ingestion_jobs`: one row per stage (`counts.stage` = `text_extraction` or `chunking`), `status` `running` → `completed` or `failed`, linked by `knowledge_document_id`.

None of these is `ready` or `completed`, so the hybrid search (`app/rag`) cannot return a document until the later indexing and activation stories mark it ready.

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
```

## Tests

```
pytest tests/ingestion                     # fast; fake OCR engine and fake DB session
$env:RUN_OCR_TESTS="1"; pytest tests/ingestion/test_ingestion_real_ocr.py -s   # real EasyOCR
```

The full flow (upload through the API → background extraction → chunking → rows in PostgreSQL) was also run against a real PostgreSQL 16 database during development, including `alembic upgrade` / `downgrade` of migration `c4d8e2f1a7b3`.
