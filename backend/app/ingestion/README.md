# Ingestion: document text extraction and OCR

Jira story: *Implement document text extraction and OCR* (Sprint 2).
BRD references: §5.2 ingestion flow, §10.1 pipeline steps, FR-016 and FR-021.

## Where this fits

```
upload (next story) ──► [ THIS STORY ]                                  ──► clean ► chunk ► embed ► Qdrant
                         validate ► extract text ► OCR if needed ► record
```

## Files

| File | Responsibility |
|---|---|
| `config.py` | `IngestionSettings`, read from `INGESTION_*` variables in `backend/.env` |
| `errors.py` | `ExtractionError` and its stable error codes |
| `extraction_types.py` | `PageText`, `ExtractionResult`: text kept **page by page** |
| `file_validation.py` | Size, extension, magic bytes, DOCX zip check, SHA-256 |
| `text_quality.py` | Decides whether native text is "insufficient" (too little or garbled) |
| `loaders/pdf_loader.py` | PyMuPDF: native text per page, and draws a page as a PNG for OCR |
| `loaders/docx_loader.py` | python-docx: paragraphs and tables in order, page breaks |
| `loaders/txt_loader.py` | Encoding detection, form-feed pages |
| `loaders/image_loader.py` | PNG, JPEG and multi-page TIFF frames |
| `ocr.py` | `OcrEngine` interface and `EasyOcrEngine` |
| `extractor.py` | `DocumentExtractor`: validation, loaders and the OCR decision |
| `storage.py` | Safe storage paths; saves and loads `<document_id>.extracted.json` |
| `pipeline.py` | `run_extraction()`: updates `knowledge_documents` and `ingestion_jobs` |
| `cli.py` | `python -m app.ingestion.cli extract <file>` and `... run <document_id>` |

## How each acceptance criterion is met

| Acceptance criterion | Where |
|---|---|
| Text extracted from supported formats (PDF, DOCX, TXT, PNG, JPEG, TIFF) | `loaders/*`, `extractor.py` |
| OCR when normal extraction is insufficient | `text_quality.assess_text` and `DocumentExtractor._ocr_pdf_page` |
| Page references preserved where available | `PageText.page_number` and `ExtractionResult.page_numbers_reliable` |
| Extraction failures recorded | `pipeline.run_extraction`: `ingestion_jobs.status`, `error_summary`, `counts["error"]` |
| Empty or corrupted documents identified | `file_validation.py`, loaders, `_ensure_not_empty`, which set the `empty` or `corrupted` status |

## Status values

`knowledge_documents.processing_status`:
`uploaded` → `extracting` → `extracted`, or one of `empty`, `corrupted`, `extraction_failed`.

`ingestion_jobs.status`: `running` → `completed` or `failed`.

None of these is `ready` or `completed`, so the hybrid search (`app/rag`) cannot return a document until the later chunking and indexing stories mark it ready.

## Settings (`backend/.env`, all optional)

```
INGESTION_STORAGE_DIR=storage/documents
INGESTION_EXTRACTED_DIR=storage/extracted
INGESTION_MAX_FILE_SIZE_MB=50
INGESTION_MAX_PAGES=2000
INGESTION_MIN_NATIVE_CHARS_PER_PAGE=50
INGESTION_MIN_TEXT_QUALITY_RATIO=0.6
INGESTION_OCR_ENABLED=true
INGESTION_OCR_LANGUAGES=["en"]
INGESTION_OCR_GPU=false
INGESTION_OCR_DPI=300
INGESTION_OCR_LOW_CONFIDENCE_WARNING=0.5
```

## Tests

```
pytest tests/ingestion                     # fast, uses a fake OCR engine
$env:RUN_OCR_TESTS="1"; pytest tests/ingestion/test_ingestion_real_ocr.py -s   # real EasyOCR
```
