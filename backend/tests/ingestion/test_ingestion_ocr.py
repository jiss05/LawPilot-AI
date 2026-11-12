"""
Acceptance criterion: "OCR is applied when normal text extraction is
insufficient."

We check both directions: OCR runs on pages that need it, and does NOT
run on pages that already have good text (OCR is slow, so it must be
used only where it helps).
"""

import pytest

from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import ExtractionMethod
from app.ingestion.extractor import DocumentExtractor
from app.ingestion.ocr import detections_to_result
from app.ingestion.text_quality import assess_text

from .helpers import LEGAL_TEXT, FakeOcrEngine, make_pdf, make_png


def test_ocr_only_on_scanned_page_of_mixed_pdf(settings, fake_ocr, tmp_path):
    # page 1 = real text, page 2 = scanned image, page 3 = real text
    path = make_pdf(tmp_path / "mixed.pdf", [LEGAL_TEXT, None, LEGAL_TEXT])
    result = DocumentExtractor(settings, fake_ocr).extract(path)

    methods = [p.method for p in result.pages]
    assert methods == [ExtractionMethod.NATIVE, ExtractionMethod.OCR, ExtractionMethod.NATIVE]
    assert fake_ocr.calls == 1

    scanned = result.pages[1]
    assert scanned.page_number == 2  # page reference survives OCR
    assert scanned.ocr_confidence == pytest.approx(0.91)
    assert "native_too_little_text" in scanned.warnings

    summary = result.summary()
    assert summary["pages_ocr"] == 1 and summary["pages_native"] == 2


def test_low_confidence_ocr_is_flagged(settings, tmp_path):
    shaky = FakeOcrEngine(confidence=0.2)
    path = make_pdf(tmp_path / "faded.pdf", [None])
    page = DocumentExtractor(settings, shaky).extract(path).pages[0]
    assert "low_ocr_confidence" in page.warnings


def test_ocr_disabled_records_warning(settings, fake_ocr, tmp_path):
    no_ocr = settings.model_copy(update={"ocr_enabled": False})
    path = make_pdf(tmp_path / "mixed.pdf", [LEGAL_TEXT, None])
    result = DocumentExtractor(no_ocr, fake_ocr).extract(path)
    assert fake_ocr.calls == 0
    assert "ocr_disabled" in result.pages[1].warnings
    assert result.pages[1].method == ExtractionMethod.NONE


def test_ocr_failure_on_one_page_does_not_lose_the_document(settings, tmp_path):
    class BrokenOcr:
        def read_image(self, image_png):
            raise ExtractionError(ExtractionErrorCode.OCR_FAILED, "boom")

    path = make_pdf(tmp_path / "mixed.pdf", [LEGAL_TEXT, None])
    result = DocumentExtractor(settings, BrokenOcr()).extract(path)
    assert result.pages[0].method == ExtractionMethod.NATIVE
    assert "ocr_failed" in result.pages[1].warnings


def test_image_without_ocr_available_fails_clearly(settings, tmp_path):
    no_ocr = settings.model_copy(update={"ocr_enabled": False})
    with pytest.raises(ExtractionError) as info:
        DocumentExtractor(no_ocr).extract(make_png(tmp_path / "scan.png"))
    assert info.value.code == ExtractionErrorCode.OCR_UNAVAILABLE


# ---------------------- text-quality heuristic ----------------------------
@pytest.mark.parametrize(
    "text, sufficient, reason",
    [
        (LEGAL_TEXT, True, None),
        ("Page 3", False, "too_little_text"),
        ("", False, "too_little_text"),
        ("�" * 80 + "ab", False, "garbled_text"),
        ("धारा 302 हत्या के लिए दंड " * 5, True, None),  # Hindi is real text
    ],
)
def test_assess_text(text, sufficient, reason):
    assessment = assess_text(text, min_chars=50, min_quality_ratio=0.6)
    assert assessment.sufficient is sufficient
    assert assessment.reason == reason


# ---------------------- EasyOCR output -> lines ---------------------------
def test_detections_rebuilt_in_reading_order():
    def box(x, y, w=50, h=20):
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    # Deliberately shuffled, as EasyOCR may return them.
    detections = [
        (box(120, 52), "Act,", 0.8),
        (box(10, 10), "Indian", 0.9),
        (box(70, 12), "Contract", 0.9),
        (box(10, 50), "Section", 0.7),
        (box(70, 50), "73", 0.6),
    ]
    result = detections_to_result(detections)
    assert result.text == "Indian Contract\nSection 73 Act,"
    assert result.box_count == 5
    assert 0.6 < result.confidence < 0.9


def test_no_detections_means_no_text():
    result = detections_to_result([])
    assert result.text == "" and result.confidence is None
