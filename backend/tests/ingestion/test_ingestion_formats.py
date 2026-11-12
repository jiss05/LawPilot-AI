"""
Acceptance criteria:
  * "Text is extracted from supported document formats."
  * "Page references are preserved where available."
"""

import pytest

from app.ingestion.extraction_types import ExtractionMethod, FileType
from app.ingestion.extractor import DocumentExtractor

from .helpers import LEGAL_TEXT, make_docx, make_pdf, make_png


@pytest.fixture
def extractor(settings, fake_ocr):
    return DocumentExtractor(settings, ocr_engine=fake_ocr)


# ----------------------------- PDF ----------------------------------------
def test_pdf_text_extracted_with_page_numbers(extractor, fake_ocr, tmp_path):
    texts = [f"PAGE {n}. {LEGAL_TEXT}" for n in (1, 2, 3)]
    result = extractor.extract(make_pdf(tmp_path / "act.pdf", texts))

    assert result.file_type == FileType.PDF
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert result.page_numbers_reliable is True
    for number, page in enumerate(result.pages, start=1):
        assert f"PAGE {number}." in page.text  # right text on the right page
        assert page.method == ExtractionMethod.NATIVE
    assert fake_ocr.calls == 0  # good native text -> OCR never used


# ----------------------------- DOCX ---------------------------------------
def test_docx_paragraphs_tables_and_page_breaks(extractor, tmp_path):
    path = make_docx(
        tmp_path / "petition.docx",
        pages=[["IN THE HIGH COURT OF KERALA", LEGAL_TEXT], ["PRAYER", "Grant relief."]],
        table_rows=[["Item", "Fee"], ["Court fee", "Rs. 500"]],
    )
    result = extractor.extract(path)

    assert result.file_type == FileType.DOCX
    assert [p.page_number for p in result.pages] == [1, 2]
    assert result.page_numbers_reliable is False  # estimated from breaks
    assert "docx_page_numbers_estimated" in result.warnings

    first = result.pages[0].text
    assert "HIGH COURT OF KERALA" in first
    assert "Court fee | Rs. 500" in first  # table kept, in order
    assert first.index("HIGH COURT") < first.index("Court fee")
    assert "PRAYER" in result.pages[1].text


def test_docx_without_breaks_has_no_page_number(extractor, tmp_path):
    path = make_docx(tmp_path / "note.docx", pages=[[LEGAL_TEXT]])
    result = extractor.extract(path)
    assert [p.page_number for p in result.pages] == [None]
    assert "no_page_information" in result.warnings


# ----------------------------- TXT ----------------------------------------
def test_txt_utf8(extractor, tmp_path):
    path = tmp_path / "act.txt"
    path.write_text("धारा 302 - " + LEGAL_TEXT, encoding="utf-8")
    result = extractor.extract(path)
    assert "धारा 302" in result.full_text  # Hindi survives
    assert result.pages[0].page_number is None


def test_txt_windows_1252_with_section_sign(extractor, tmp_path):
    path = tmp_path / "old.txt"
    path.write_bytes(("§ 73 " + LEGAL_TEXT + " “quoted”").encode("cp1252"))
    result = extractor.extract(path)
    assert "§ 73" in result.full_text
    assert "“quoted”" in result.full_text
    assert "decoded_as_cp1252" in result.warnings


def test_txt_utf16_from_notepad(extractor, tmp_path):
    path = tmp_path / "notepad.txt"
    path.write_bytes(LEGAL_TEXT.encode("utf-16"))  # includes BOM
    assert "Section 73" in extractor.extract(path).full_text


def test_txt_form_feeds_become_pages(extractor, tmp_path):
    path = tmp_path / "pdftotext.txt"
    path.write_text(f"one {LEGAL_TEXT}\fTWO {LEGAL_TEXT}\f", encoding="utf-8")
    result = extractor.extract(path)
    assert [p.page_number for p in result.pages] == [1, 2]
    assert result.pages[1].text.startswith("TWO")
    assert result.page_numbers_reliable is True


def test_txt_windows_line_endings_normalised(extractor, tmp_path):
    path = tmp_path / "crlf.txt"
    path.write_bytes(f"line one {LEGAL_TEXT}\r\nline two".encode())
    assert "\r" not in extractor.extract(path).full_text


# ----------------------------- images -------------------------------------
def test_png_goes_through_ocr(extractor, fake_ocr, tmp_path):
    result = extractor.extract(make_png(tmp_path / "scan.png"))
    assert result.file_type == FileType.PNG
    assert result.pages[0].method == ExtractionMethod.OCR
    assert result.pages[0].page_number == 1
    assert result.pages[0].ocr_confidence == pytest.approx(0.91)
    assert fake_ocr.calls == 1


def test_multipage_tiff_keeps_page_numbers(extractor, fake_ocr, tmp_path):
    result = extractor.extract(make_png(tmp_path / "record.tiff", frames=3))
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert fake_ocr.calls == 3


def test_extension_is_case_insensitive(extractor, tmp_path):
    path = make_pdf(tmp_path / "UPPER.PDF", [LEGAL_TEXT])
    assert extractor.extract(path).file_type == FileType.PDF
