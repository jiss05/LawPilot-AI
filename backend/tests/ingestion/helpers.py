"""
Test helpers: a fake OCR engine and functions that BUILD test documents.

Test files are created on the fly with PyMuPDF, python-docx and Pillow,
inside pytest's temporary folder, so no binary files are committed to git.
"""

from __future__ import annotations

import io
from pathlib import Path

import docx
import pymupdf
from PIL import Image, ImageDraw

from app.ingestion.ocr import OcrResult

LEGAL_TEXT = (
    "Section 73. Compensation for loss or damage caused by breach of contract. "
    "When a contract has been broken, the party who suffers by such breach is "
    "entitled to receive compensation."
)


class FakeOcrEngine:
    """Pretends to be EasyOCR."""

    def __init__(self, text: str = "OCR TEXT FROM SCANNED PAGE " * 4, confidence: float = 0.91):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def read_image(self, image_png: bytes) -> OcrResult:
        assert image_png.startswith(b"\x89PNG"), "OCR must receive a PNG image"
        self.calls += 1
        if not self.text:
            return OcrResult("", None, 0)
        return OcrResult(self.text, self.confidence, 3)


# ---------------------------------------------------------------------------
# File builders
# ---------------------------------------------------------------------------
def make_pdf(path: Path, page_texts: list[str | None], password: str | None = None) -> Path:
    """
    Build a PDF. Each list item is one page:
      * a string -> a page with real (selectable) text
      * None     -> a page with only a picture, like a scanned page
    """
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        if text is None:
            # Draw an image of text: no text layer, so native extraction
            # finds nothing, exactly like a scanner output.
            image = Image.new("RGB", (400, 100), "white")
            ImageDraw.Draw(image).text((10, 40), "SCANNED TEXT", fill="black")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            page.insert_image(pymupdf.Rect(50, 50, 450, 150), stream=buffer.getvalue())
        else:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
    if password:
        document.save(
            path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password + "-owner",
        )
    else:
        document.save(path)
    document.close()
    return path


def make_docx(path: Path, pages: list[list[str]], table_rows: list[list[str]] | None = None) -> Path:
    """Build a DOCX; a manual page break is inserted between page groups."""
    document = docx.Document()
    for index, paragraphs in enumerate(pages):
        if index > 0:
            document.add_page_break()
        for paragraph in paragraphs:
            document.add_paragraph(paragraph)
        if index == 0 and table_rows:
            table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
            for r, row in enumerate(table_rows):
                for c, value in enumerate(row):
                    table.cell(r, c).text = value
    document.save(path)
    return path


def make_png(path: Path, frames: int = 1) -> Path:
    images = [Image.new("RGB", (300, 80), "white") for _ in range(frames)]
    for image in images:
        ImageDraw.Draw(image).text((10, 30), "SCANNED", fill="black")
    if frames == 1:
        images[0].save(path)
    else:  # multi-page TIFF
        images[0].save(path, save_all=True, append_images=images[1:])
    return path


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------
def pages_result(pages, file_type="pdf", reliable=True):
    """Build an ExtractionResult straight from strings (one string per page)."""
    from app.ingestion.extraction_types import ExtractionMethod, ExtractionResult, FileType, PageText

    return ExtractionResult(
        FileType(file_type),
        [PageText(n if reliable else None, text, ExtractionMethod.NATIVE) for n, text in enumerate(pages, 1)],
        page_numbers_reliable=reliable,
    )


LONG_SECTION_BODY = " ".join(
    f"Sentence {i} explains a further consequence of the breach in plain terms." for i in range(1, 40)
)


def make_statute_pdf(path: Path, amendment: str | None = None) -> Path:
    """
    A 3-page statute-style PDF like the ones from India Code: a running
    header on every page, "- n -" page numbers, chapters, sections,
    sub-sections, clauses, an Explanation, and Section 73 long enough to be
    split and running from page 2 onto page 3.

    `amendment` adds one more paragraph on page 3, to build a NEW EDITION
    of the same Act for versioning tests.
    """
    pages = [
        ["CHAPTER I", "PRELIMINARY",
         "1. Short title, extent and commencement. - (1) This Act may be called the Sample Contract Act, 1872.",
         "(2) It extends to the whole of India.",
         "2. Interpretation-clause. - In this Act the following words are used in the following senses: -",
         "(a) when one person signifies to another his willingness to do anything, he is said to make a proposal;",
         "(b) when the person to whom the proposal is made signifies his assent thereto, the proposal is said to be accepted;"],
        ["CHAPTER VI", "OF THE CONSEQUENCES OF BREACH OF CONTRACT",
         "73. Compensation for loss or damage caused by breach of contract. - When a contract has been broken, "
         "the party who suffers by such breach is entitled to receive compensation. " + LONG_SECTION_BODY[:900]],
        [LONG_SECTION_BODY[900:],
         "Explanation. - In estimating the loss, the means which existed of remedying the inconvenience must be taken into account.",
         "74. Compensation for breach of contract where penalty stipulated for. - When a contract has been broken, "
         "the party complaining of the breach is entitled to reasonable compensation."]
        + ([amendment] if amendment else []),
    ]
    document = pymupdf.open()
    for number, paragraphs in enumerate(pages, start=1):
        page = document.new_page()
        page.insert_text((60, 40), "THE SAMPLE CONTRACT ACT, 1872", fontsize=9)  # running header
        y = 70
        for paragraph in paragraphs:
            rect = pymupdf.Rect(60, y, 540, 800)
            unused = page.insert_textbox(rect, paragraph, fontsize=10.5)
            y += (rect.height - unused) + 26
        page.insert_text((290, 820), f"- {number} -", fontsize=9)  # page number footer
    document.save(path)
    document.close()
    return path
