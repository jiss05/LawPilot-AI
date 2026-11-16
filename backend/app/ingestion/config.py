"""
Configuration for the document ingestion pipeline.

WHY A SEPARATE SETTINGS CLASS?
------------------------------
The authentication branch already defines `app/core/config.py`. Keeping the
ingestion settings in their own small class means this feature can be merged
without touching that file (no merge conflicts), and every ingestion setting
lives in one obvious place.

HOW VALUES ARE LOADED
---------------------
`pydantic-settings` reads values in this order (later wins):
    1. the defaults written below
    2. the `backend/.env` file
    3. real environment variables

Every variable uses the prefix `INGESTION_`. For example, to change the
OCR resolution you would add this line to `backend/.env`:

    INGESTION_OCR_DPI=200

List values (like OCR languages) must be written as JSON in the .env file:

    INGESTION_OCR_LANGUAGES=["en","hi"]
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The `backend/` folder, worked out from this file's own location
# (backend/app/ingestion/config.py -> three levels up). Using it for the
# defaults means the paths are the same no matter which folder you start
# uvicorn, pytest or the CLI from.
BACKEND_DIR = Path(__file__).resolve().parents[2]

class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INGESTION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unrelated keys such as DATABASE_URL
    )

    # ------------------------------------------------------------------ #
    # Storage
    # ------------------------------------------------------------------ #
    # Folder where the original uploaded files are kept. The upload API
    # (app/services/knowledge_source_service.py) saves files here, and the
    # `knowledge_documents.storage_key` column holds the file name RELATIVE
    # to this folder, e.g. "3f6c2a9e-....pdf".
    # (Sprint 2 fix: upload and extraction now share this one setting.)
    storage_dir: Path = BACKEND_DIR / "legal_documents"

    # Folder where the page-by-page extraction output (JSON) is saved.
    # The chunking step reads these files.
    extracted_dir: Path = BACKEND_DIR / "storage" / "extracted"

    # ------------------------------------------------------------------ #
    # File validation limits (BRD §12: "enforce file-size and page-count
    # limits")
    # ------------------------------------------------------------------ #
    max_file_size_mb: int = 50
    max_pages: int = 2000

    # ------------------------------------------------------------------ #
    # "Is the normal text good enough?" thresholds
    # ------------------------------------------------------------------ #
    # A PDF page with fewer meaningful characters than this is treated as
    # "insufficient" and sent to OCR. Scanned pages usually have 0 chars.
    min_native_chars_per_page: int = 50

    # Share of characters that must look like real text (letters, digits,
    # spaces, normal punctuation). Broken font encodings produce junk such
    # as "��" or "(cid:12)(cid:45)"; below this ratio we try OCR.
    min_text_quality_ratio: float = 0.6

    # If the WHOLE document has fewer characters than this after native
    # extraction AND OCR, it is reported as an empty document.
    min_document_chars: int = 20

    # ------------------------------------------------------------------ #
    # OCR (EasyOCR)
    # ------------------------------------------------------------------ #
    ocr_enabled: bool = True
    ocr_languages: list[str] = ["en"]
    # Set to true only if you have an NVIDIA GPU with CUDA-enabled PyTorch.
    ocr_gpu: bool = False
    # Resolution used when turning a PDF page into an image for OCR.
    # 300 DPI is the usual sweet spot for printed text; higher = slower.
    ocr_dpi: int = 300
    # Average OCR confidence (0..1) below which we attach a warning so an
    # administrator can review the page (BRD §17: "OCR quality checks").
    ocr_low_confidence_warning: float = 0.5

    # ------------------------------------------------------------------ #
    # Chunking (see app/ingestion/chunking/)
    # ------------------------------------------------------------------ #
    # Target maximum size of one chunk, in APPROXIMATE tokens. A "token" is
    # the unit language models count in; for English, 1 token is roughly
    # 4 characters or 3/4 of a word. We estimate instead of counting
    # exactly because the embedding model is not chosen yet.
    chunk_max_tokens: int = 400
    # When a long section is split, this many tokens from the end of one
    # part are repeated at the start of the next, so a sentence that
    # depends on the previous one still makes sense on its own.
    chunk_overlap_tokens: int = 50
    # Judgment paragraphs shorter than this are merged with their
    # neighbours (statute sections are never merged, to keep citations
    # exact).
    chunk_min_tokens: int = 40
    # A line that appears at the top or bottom of at least this share of
    # pages is treated as a running header/footer and removed.
    header_footer_min_ratio: float = 0.5


@lru_cache
def get_ingestion_settings() -> IngestionSettings:
    """
    Return a single shared settings object.

    `lru_cache` means the .env file is read only once, the first time this
    function is called. Tests can pass their own IngestionSettings object
    to the extractor/pipeline instead of using this function.
    """
    return IngestionSettings()
