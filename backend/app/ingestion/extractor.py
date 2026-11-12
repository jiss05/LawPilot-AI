"""
DocumentExtractor: the single entry point for "give me the text of this file".

It ties the previous pieces together:

    validate_file()            -> is the file safe, supported and intact?
    loader (pdf/docx/txt/img)  -> native text, page by page
    assess_text()              -> is a page's native text sufficient?
    OCR engine                 -> read insufficient pages from an image
    final check                -> is the whole document empty?

It knows nothing about the database. That makes it usable from the CLI,
from tests and from the pipeline (which does the database work).

THE OCR DECISION FOR A PDF PAGE
-------------------------------
    native text sufficient? --yes--> keep native              (method=native)
           |
           no
           v
    OCR enabled? --no--> keep native + warning "ocr_disabled"
           |
          yes
           v
    run OCR on a 300-DPI image of the page
           v
    OCR found more text than native? --yes--> use OCR text    (method=ocr)
           |                                  (+ confidence)
           no
           v
    keep native (if any) + warning "ocr_no_improvement",
    or mark page "blank_page" if both are empty               (method=none)
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import (
    ExtractionMethod,
    ExtractionResult,
    FileType,
    PageText,
)
from app.ingestion.file_validation import validate_file
from app.ingestion.loaders import docx_loader, image_loader, pdf_loader, txt_loader
from app.ingestion.ocr import OcrEngine, get_default_ocr_engine
from app.ingestion.text_quality import assess_text

logger = logging.getLogger(__name__)


class DocumentExtractor:
    def __init__(
        self,
        settings: IngestionSettings | None = None,
        ocr_engine: OcrEngine | None = None,
    ) -> None:
        self.settings = settings or get_ingestion_settings()
        # If no engine is given we create the real EasyOCR one lazily,
        # only when the first page actually needs OCR.
        self._ocr_engine = ocr_engine

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def extract(self, path: Path, expected_sha256: str | None = None) -> ExtractionResult:
        """
        Extract text from `path`.

        Returns an ExtractionResult, or raises ExtractionError with a code
        explaining exactly why extraction was impossible.
        """
        path = Path(path)
        file_type = validate_file(path, self.settings, expected_sha256)
        logger.info("Extracting %s as %s", path.name, file_type.value)

        if file_type == FileType.PDF:
            result = self._extract_pdf(path)
        elif file_type == FileType.DOCX:
            pages, found = docx_loader.extract_docx_pages(path)
            warnings = (
                ["docx_page_numbers_estimated"] if found else ["no_page_information"]
            )
            result = ExtractionResult(file_type, pages, False, warnings)
        elif file_type == FileType.TXT:
            pages, found, warnings = txt_loader.extract_txt_pages(path)
            if not found:
                warnings.append("no_page_information")
            result = ExtractionResult(file_type, pages, found, warnings)
        elif file_type.is_image:
            result = self._extract_image(path, file_type)
        else:  # pragma: no cover - validate_file only returns known types
            raise ExtractionError(
                ExtractionErrorCode.UNSUPPORTED_FORMAT, f"No loader for {file_type}"
            )

        self._ensure_not_empty(result)
        return result

    # ------------------------------------------------------------------ #
    # PDF: native first, OCR per insufficient page
    # ------------------------------------------------------------------ #
    def _extract_pdf(self, path: Path) -> ExtractionResult:
        pages = pdf_loader.extract_native_pages(path, self.settings.max_pages)

        final_pages: list[PageText] = []
        for page in pages:
            assessment = assess_text(
                page.text,
                self.settings.min_native_chars_per_page,
                self.settings.min_text_quality_ratio,
            )
            if assessment.sufficient:
                final_pages.append(page)
                continue

            logger.info(
                "Page %s needs OCR (%s, %s chars)",
                page.page_number,
                assessment.reason,
                assessment.char_count,
            )
            final_pages.append(
                self._ocr_pdf_page(path, page, assessment.reason or "insufficient")
            )

        return ExtractionResult(FileType.PDF, final_pages, page_numbers_reliable=True)

    def _ocr_pdf_page(self, path: Path, native: PageText, reason: str) -> PageText:
        """Try OCR on one PDF page and decide which text to keep."""
        page_number = native.page_number
        warnings = list(native.warnings) + [f"native_{reason}"]

        if not self.settings.ocr_enabled:
            return self._keep_native(native, warnings + ["ocr_disabled"])

        try:
            image = pdf_loader.render_page_png(path, page_number, self.settings.ocr_dpi)
            ocr = self._ocr().read_image(image)
        except ExtractionError as exc:
            # OCR_UNAVAILABLE / OCR_FAILED for ONE page should not lose the
            # rest of the document: record it on the page and carry on.
            logger.warning("OCR failed on page %s: %s", page_number, exc)
            return self._keep_native(native, warnings + [exc.code.value.lower()])
        except Exception as exc:
            logger.warning("Page %s could not be rendered for OCR: %s", page_number, exc)
            return self._keep_native(native, warnings + ["ocr_failed"])

        ocr_page = PageText(
            page_number, ocr.text, ExtractionMethod.OCR, ocr.confidence, warnings
        )
        if ocr_page.char_count > native.char_count:
            self._flag_low_confidence(ocr_page)
            return ocr_page

        return self._keep_native(native, warnings + ["ocr_no_improvement"])

    # ------------------------------------------------------------------ #
    # Images: every page is OCR
    # ------------------------------------------------------------------ #
    def _extract_image(self, path: Path, file_type: FileType) -> ExtractionResult:
        if not self.settings.ocr_enabled:
            raise ExtractionError(
                ExtractionErrorCode.OCR_UNAVAILABLE,
                "Scanned images need OCR, but OCR is disabled in settings.",
            )

        images = image_loader.load_page_images(path, self.settings.max_pages)
        engine = self._ocr()  # an ExtractionError here fails the whole file
        pages: list[PageText] = []
        for page_number, image in enumerate(images, start=1):
            ocr = engine.read_image(image)
            page = PageText(page_number, ocr.text, ExtractionMethod.OCR, ocr.confidence)
            if page.is_empty:
                page.method = ExtractionMethod.NONE
                page.warnings.append("blank_page")
            else:
                self._flag_low_confidence(page)
            pages.append(page)
        return ExtractionResult(file_type, pages, page_numbers_reliable=True)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _ocr(self) -> OcrEngine:
        if self._ocr_engine is None:
            self._ocr_engine = get_default_ocr_engine(
                self.settings.ocr_languages, self.settings.ocr_gpu
            )
        return self._ocr_engine

    @staticmethod
    def _keep_native(native: PageText, warnings: list[str]) -> PageText:
        page = PageText(native.page_number, native.text, native.method, None, warnings)
        if page.is_empty:
            page.method = ExtractionMethod.NONE
            page.warnings.append("blank_page")
        return page

    def _flag_low_confidence(self, page: PageText) -> None:
        if (
            page.ocr_confidence is not None
            and page.ocr_confidence < self.settings.ocr_low_confidence_warning
        ):
            page.warnings.append("low_ocr_confidence")

    def _ensure_not_empty(self, result: ExtractionResult) -> None:
        """
        Acceptance criterion: "Empty documents are identified."
        A file can be valid and still contain nothing readable, e.g. a PDF
        of blank pages, or a scan so poor OCR finds nothing.
        """
        if result.total_chars < self.settings.min_document_chars:
            raise ExtractionError(
                ExtractionErrorCode.NO_TEXT_FOUND,
                "No readable text was found in the document, even after OCR.",
                details={
                    "pages_total": result.page_count,
                    "total_chars": result.total_chars,
                    "page_warnings": result.summary()["warnings"],
                },
            )
