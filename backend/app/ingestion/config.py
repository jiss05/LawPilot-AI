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
    # Folder where the original uploaded files are kept. The
    # `knowledge_documents.storage_key` column holds a path RELATIVE to
    # this folder, e.g. "acts/ipc_1860.pdf".
    storage_dir: Path = Path("storage/documents")

    # Folder where the page-by-page extraction output (JSON) is saved.
    # The chunking story will read these files next sprint.
    extracted_dir: Path = Path("storage/extracted")

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


@lru_cache
def get_ingestion_settings() -> IngestionSettings:
    """
    Return a single shared settings object.

    `lru_cache` means the .env file is read only once, the first time this
    function is called. Tests can pass their own IngestionSettings object
    to the extractor/pipeline instead of using this function.
    """
    return IngestionSettings()
