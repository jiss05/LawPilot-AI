"""
Acceptance criterion: "Empty or corrupted documents are identified."

These tests feed deliberately bad files to the extractor and check that
each one is rejected with the RIGHT error code.
"""

import zipfile

import pytest

from app.ingestion.errors import ExtractionError, ExtractionErrorCode as Code
from app.ingestion.extractor import DocumentExtractor
from app.ingestion.file_validation import compute_sha256, validate_file
from app.ingestion.extraction_types import FileType

from .helpers import LEGAL_TEXT, FakeOcrEngine, make_pdf


def expect_error(extractor, path, code, **kwargs):
    with pytest.raises(ExtractionError) as info:
        extractor.extract(path, **kwargs)
    assert info.value.code == code, f"expected {code}, got {info.value}"
    return info.value


@pytest.fixture
def extractor(settings, fake_ocr):
    return DocumentExtractor(settings, ocr_engine=fake_ocr)


def test_missing_file(extractor, tmp_path):
    expect_error(extractor, tmp_path / "nope.pdf", Code.FILE_NOT_FOUND)


def test_zero_byte_file_is_empty(extractor, tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    expect_error(extractor, path, Code.EMPTY_FILE)


def test_unsupported_extension(extractor, tmp_path):
    path = tmp_path / "data.xlsx"
    path.write_bytes(b"PK\x03\x04whatever")
    expect_error(extractor, path, Code.UNSUPPORTED_FORMAT)


def test_text_file_renamed_to_pdf_is_rejected(extractor, tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("I am not really a PDF")
    expect_error(extractor, path, Code.SIGNATURE_MISMATCH)


def test_pdf_with_valid_header_but_broken_body_is_corrupted(extractor, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)
    expect_error(extractor, path, Code.CORRUPTED_FILE)


def test_truncated_pdf_is_detected(extractor, tmp_path):
    good = make_pdf(tmp_path / "good.pdf", [LEGAL_TEXT] * 3)
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(good.read_bytes()[:200])  # cut off mid-file
    expect_error(extractor, truncated, Code.CORRUPTED_FILE)


def test_password_protected_pdf(extractor, tmp_path):
    path = make_pdf(tmp_path / "locked.pdf", [LEGAL_TEXT], password="secret")
    expect_error(extractor, path, Code.ENCRYPTED_FILE)


def test_zip_that_is_not_a_docx(extractor, tmp_path):
    path = tmp_path / "archive.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "hello")
    expect_error(extractor, path, Code.SIGNATURE_MISMATCH)


def test_truncated_docx_is_corrupted(extractor, tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"PK\x03\x04" + b"\x01" * 100)
    expect_error(extractor, path, Code.CORRUPTED_FILE)


def test_corrupted_png(extractor, tmp_path):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    expect_error(extractor, path, Code.CORRUPTED_FILE)


def test_binary_file_named_txt(extractor, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"abc\x00\x01\x02def")
    expect_error(extractor, path, Code.SIGNATURE_MISMATCH)


def test_file_too_large(settings, fake_ocr, tmp_path):
    small_limit = settings.model_copy(update={"max_file_size_mb": 0})
    path = make_pdf(tmp_path / "doc.pdf", [LEGAL_TEXT])
    expect_error(DocumentExtractor(small_limit, fake_ocr), path, Code.FILE_TOO_LARGE)


def test_too_many_pages(settings, fake_ocr, tmp_path):
    limited = settings.model_copy(update={"max_pages": 2})
    path = make_pdf(tmp_path / "long.pdf", [LEGAL_TEXT] * 3)
    expect_error(DocumentExtractor(limited, fake_ocr), path, Code.TOO_MANY_PAGES)


def test_checksum_mismatch_means_file_changed(extractor, tmp_path):
    path = make_pdf(tmp_path / "doc.pdf", [LEGAL_TEXT])
    expect_error(extractor, path, Code.CHECKSUM_MISMATCH, expected_sha256="0" * 64)


def test_checksum_match_passes(settings, tmp_path):
    path = make_pdf(tmp_path / "doc.pdf", [LEGAL_TEXT])
    assert validate_file(path, settings, compute_sha256(path)) == FileType.PDF


def test_pdf_of_blank_pages_is_reported_empty(settings, tmp_path):
    blank_ocr = FakeOcrEngine(text="")  # OCR also finds nothing
    path = make_pdf(tmp_path / "blank.pdf", ["", ""])
    error = expect_error(DocumentExtractor(settings, blank_ocr), path, Code.NO_TEXT_FOUND)
    assert error.details["pages_total"] == 2
    assert blank_ocr.calls == 2  # OCR WAS tried before giving up


def test_whitespace_only_txt_is_empty(extractor, tmp_path):
    path = tmp_path / "spaces.txt"
    path.write_text("   \n\n\t  ")
    expect_error(extractor, path, Code.NO_TEXT_FOUND)
