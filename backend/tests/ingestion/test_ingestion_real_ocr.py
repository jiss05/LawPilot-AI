"""
OPTIONAL end-to-end test with the REAL EasyOCR engine.

Skipped by default because it is slow and, the first time, downloads
about 100 MB of model files. Run it on purpose:

    PowerShell:   $env:RUN_OCR_TESTS="1"; pytest tests/ingestion/test_ingestion_real_ocr.py -s
    bash:         RUN_OCR_TESTS=1 pytest tests/ingestion/test_ingestion_real_ocr.py -s
"""

import io
import os

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ingestion.extraction_types import ExtractionMethod
from app.ingestion.extractor import DocumentExtractor

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OCR_TESTS") != "1",
    reason="set RUN_OCR_TESTS=1 to run the slow real-EasyOCR test",
)


def test_easyocr_reads_a_scanned_pdf_page(settings, tmp_path):
    pytest.importorskip("easyocr")

    # Draw large, clear text on an image, then put the image in a PDF,
    # which is what a scanner produces.
    image = Image.new("RGB", (1600, 300), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 64)  # Windows
    except OSError:
        font = ImageFont.load_default(size=64)
    ImageDraw.Draw(image).text((40, 100), "INDIAN CONTRACT ACT 1872", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    document = pymupdf.open()
    page = document.new_page(width=800, height=200)
    page.insert_image(page.rect, stream=buffer.getvalue())
    path = tmp_path / "scan.pdf"
    document.save(path)

    real = settings.model_copy(update={"ocr_dpi": 200})
    result = DocumentExtractor(real).extract(path)  # no fake -> real EasyOCR

    page = result.pages[0]
    print(f"\nOCR text: {page.text!r}  confidence={page.ocr_confidence}")
    assert page.method == ExtractionMethod.OCR
    assert "CONTRACT" in page.text.upper()
    assert page.ocr_confidence and page.ocr_confidence > 0.5
