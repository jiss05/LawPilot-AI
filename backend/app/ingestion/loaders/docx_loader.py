"""
DOCX loader built on python-docx.

Install:  pip install python-docx

TWO THINGS MAKE WORD FILES TRICKY
---------------------------------
1. ORDER OF PARAGRAPHS AND TABLES
   `document.paragraphs` and `document.tables` are two separate lists, so
   using them directly would put every table at the end. Legal documents
   often have tables (schedules, fee lists), and their position matters.
   We therefore walk the document body XML in order, element by element.

2. PAGES DON'T REALLY EXIST IN A .DOCX
   Word decides where pages break when it DISPLAYS the file, based on
   fonts, margins and printer settings. The file can still contain hints:
     * <w:lastRenderedPageBreak/> - where Word broke pages the last time
       it saved the file (best guess of the real layout)
     * <w:br w:type="page"/>      - a manual page break (Ctrl+Enter)
   If we find hints we number the pages, but mark them as estimated
   (`page_numbers_reliable = False`). If there are none, page_number is
   None. This is exactly the "where available" part of the acceptance
   criterion.
"""

from __future__ import annotations

from pathlib import Path

import docx
from docx.oxml.ns import qn

from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import ExtractionMethod, PageText

# Fully-qualified XML tag names, e.g. "{http://...wordprocessingml...}p".
# `qn("w:p")` converts the short prefix form into that long form.
TAG_PARAGRAPH = qn("w:p")
TAG_TABLE = qn("w:tbl")
TAG_TEXT = qn("w:t")
TAG_TAB = qn("w:tab")
TAG_BREAK = qn("w:br")
TAG_RENDERED_BREAK = qn("w:lastRenderedPageBreak")
ATTR_BREAK_TYPE = qn("w:type")


class _PageCollector:
    """Small helper that gathers text and starts a new page on request."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]

    def write(self, text: str) -> None:
        self.pages[-1].append(text)

    def new_page(self) -> None:
        self.pages.append([])

    def texts(self) -> list[str]:
        return ["".join(parts).strip() for parts in self.pages]


def _walk_paragraph(paragraph_xml, collector: _PageCollector, use_rendered: bool) -> None:
    """Read one <w:p> element, honouring tabs, line breaks and page breaks."""
    for element in paragraph_xml.iter():
        tag = element.tag
        if tag == TAG_TEXT and element.text:
            collector.write(element.text)
        elif tag == TAG_TAB:
            collector.write("\t")
        elif tag == TAG_RENDERED_BREAK and use_rendered:
            collector.new_page()
        elif tag == TAG_BREAK:
            if element.get(ATTR_BREAK_TYPE) == "page" and not use_rendered:
                collector.new_page()
            else:
                collector.write("\n")  # ordinary line break (Shift+Enter)
    collector.write("\n")  # end of paragraph


def _walk_table(table_xml, collector: _PageCollector) -> None:
    """
    Turn a table into lines like "cell 1 | cell 2 | cell 3".
    Page breaks inside tables are ignored (rare, and keeps this simple).
    """
    for row in table_xml.iter(qn("w:tr")):
        cells = []
        for cell in row.iter(qn("w:tc")):
            cell_text = "".join(t.text or "" for t in cell.iter(TAG_TEXT))
            cells.append(cell_text.strip())
        collector.write(" | ".join(cells) + "\n")
    collector.write("\n")


def extract_docx_pages(path: Path) -> tuple[list[PageText], bool]:
    """
    Return (pages, page_numbers_found).

    `page_numbers_found` tells the extractor whether page numbers come
    from page-break hints (estimated) or are not available at all.
    """
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # broken XML, missing parts, etc.
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The Word document could not be opened; it may be damaged.",
            details={"reason": str(exc)},
        ) from exc

    body = document.element.body

    # Prefer Word's own rendered breaks; fall back to manual page breaks.
    use_rendered = bool(body.xpath(".//w:lastRenderedPageBreak"))
    has_manual = bool(body.xpath('.//w:br[@w:type="page"]'))
    page_numbers_found = use_rendered or has_manual

    collector = _PageCollector()
    for child in body.iterchildren():
        if child.tag == TAG_PARAGRAPH:
            _walk_paragraph(child, collector, use_rendered)
        elif child.tag == TAG_TABLE:
            _walk_table(child, collector)
        # Other children (section properties etc.) contain no body text.

    texts = collector.texts()

    if not page_numbers_found:
        # No page information at all -> one section without a page number.
        return [PageText(None, "\n".join(texts), ExtractionMethod.NATIVE)], False

    pages = [
        PageText(number, text, ExtractionMethod.NATIVE)
        for number, text in enumerate(texts, start=1)
    ]
    return pages, True
