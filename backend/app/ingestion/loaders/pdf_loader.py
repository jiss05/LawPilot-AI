"""
PDF loader built on PyMuPDF (BRD §5.1: "Ingestion pipeline - PyMuPDF").

PyMuPDF (imported as `pymupdf`, older name `fitz`) can:
  * read the text layer of each page   -> `page.get_text()`
  * draw a page as an image (a "pixmap") -> `page.get_pixmap()`
The second ability is why we don't need Poppler on Windows for OCR:
PyMuPDF turns a scanned page into a PNG that we hand to EasyOCR.

Install:  pip install pymupdf
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import ExtractionMethod, PageText

logger = logging.getLogger(__name__)


def open_pdf(path: Path, max_pages: int) -> pymupdf.Document:
    """
    Open a PDF and run the document-level checks.

    Raises ExtractionError for:
      * a corrupted file that PyMuPDF cannot open
      * a password-protected (encrypted) file
      * a PDF with 0 pages, or more pages than allowed
    """
    try:
        document = pymupdf.open(path, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises FileDataError / RuntimeError
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The PDF could not be opened; it may be damaged or truncated.",
            details={"reason": str(exc)},
        ) from exc

    # `needs_pass` is True when a password is required to READ the file.
    # Some PDFs are "encrypted" with an empty password; authenticate("")
    # unlocks those, so we try that before giving up.
    if document.needs_pass and not document.authenticate(""):
        document.close()
        raise ExtractionError(
            ExtractionErrorCode.ENCRYPTED_FILE,
            "The PDF is password-protected. Upload an unlocked copy.",
        )

    if document.page_count == 0:
        document.close()
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The PDF contains no pages.",
        )

    if document.page_count > max_pages:
        page_count = document.page_count
        document.close()
        raise ExtractionError(
            ExtractionErrorCode.TOO_MANY_PAGES,
            f"The PDF has {page_count} pages; the limit is {max_pages}.",
            details={"page_count": page_count, "limit": max_pages},
        )

    return document


def extract_native_pages(path: Path, max_pages: int) -> list[PageText]:
    """
    Read the text layer of every page.

    Page numbers are 1-based (humans say "page 1", Python says index 0),
    so we always store `index + 1`.

    One broken page should not throw away a 300-page judgment, so errors
    are caught PER PAGE: that page gets an empty text and a warning, and
    the extractor will try OCR on it.
    """
    pages: list[PageText] = []
    with open_pdf(path, max_pages) as document:
        for index, page in enumerate(document):
            page_number = index + 1
            try:
                # sort=True orders text blocks top-to-bottom, left-to-right,
                # which gives a natural reading order for most layouts.
                text = page.get_text("text", sort=True)
                pages.append(PageText(page_number, text, ExtractionMethod.NATIVE))
            except Exception as exc:
                logger.warning("Native text failed on page %s: %s", page_number, exc)
                pages.append(
                    PageText(
                        page_number,
                        "",
                        ExtractionMethod.NONE,
                        warnings=["native_extraction_error"],
                    )
                )
    return pages


def render_page_png(path: Path, page_number: int, dpi: int) -> bytes:
    """
    Draw one page (1-based number) as a grayscale PNG image for OCR.

    Grayscale (`csGRAY`) is a third the size of colour and OCR does not
    need colour, so it is faster and uses less memory.
    """
    with pymupdf.open(path, filetype="pdf") as document:
        if document.needs_pass:
            document.authenticate("")
        page = document[page_number - 1]
        pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        return pixmap.tobytes("png")
