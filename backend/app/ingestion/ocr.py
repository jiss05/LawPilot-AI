"""
OCR (Optical Character Recognition) with EasyOCR.

Acceptance criterion: "OCR is applied when normal text extraction is
insufficient." BRD §10.1: "Preserve page numbers and OCR confidence
information where available."

HOW EASYOCR WORKS (in one paragraph)
------------------------------------
EasyOCR runs two neural networks (on top of PyTorch):
  1. a DETECTOR that finds rectangles containing text in the image, and
  2. a RECOGNISER that reads the characters inside each rectangle.
`reader.readtext(image)` returns a list of (box, text, confidence), where
`box` is the 4 corner points of the rectangle and `confidence` is 0..1.
The first time a Reader is created it downloads its model files (about
100 MB for English) into `C:\\Users\\<you>\\.EasyOCR\\`; later runs reuse them.

WHY AN `OcrEngine` PROTOCOL?
----------------------------
The extractor depends on the small `OcrEngine` interface, not on EasyOCR
itself (the same idea as the BRD's ModelGateway for LLMs). Benefits:
  * unit tests use a fake engine: fast, and no 100 MB download,
  * we could switch to Tesseract or a cloud OCR later without changing
    the extractor.

Install:  pip install easyocr      (this also installs PyTorch, CPU build
                                    on Windows, roughly 200+ MB)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from app.ingestion.errors import ExtractionError, ExtractionErrorCode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrResult:
    text: str
    # Average confidence 0..1, weighted by text length; None if no text found.
    confidence: float | None
    # How many text boxes EasyOCR detected.
    box_count: int


class OcrEngine(Protocol):
    """Anything with this method can be used as an OCR engine."""

    def read_image(self, image_png: bytes) -> OcrResult: ...


# --------------------------------------------------------------------------
# Turning EasyOCR boxes back into readable lines
# --------------------------------------------------------------------------
# EasyOCR returns boxes in no guaranteed order. To rebuild the page text we:
#   1. sort boxes from top to bottom,
#   2. group boxes whose vertical centres are close into the same LINE,
#   3. sort each line from left to right and join the words with spaces.

def _box_geometry(box: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    """Return (left_x, centre_y, height) of a 4-point box."""
    xs = [point[0] for point in box]
    ys = [point[1] for point in box]
    return min(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys)


def detections_to_result(detections: list[tuple[Any, str, float]]) -> OcrResult:
    """Convert raw EasyOCR output into an OcrResult with natural line order."""
    items = []
    for box, text, confidence in detections:
        text = (text or "").strip()
        if not text:
            continue
        left, centre_y, height = _box_geometry(box)
        items.append((centre_y, left, height, text, float(confidence)))

    if not items:
        return OcrResult(text="", confidence=None, box_count=0)

    items.sort(key=lambda item: (item[0], item[1]))  # top-to-bottom, then left

    lines: list[list[tuple]] = []
    for item in items:
        centre_y, _, height, _, _ = item
        if lines:
            last_line = lines[-1]
            line_centre = sum(i[0] for i in last_line) / len(last_line)
            # Same line if the vertical centres are within half a box height.
            if abs(centre_y - line_centre) <= max(height, 1) / 2:
                last_line.append(item)
                continue
        lines.append([item])

    text_lines = [
        " ".join(i[3] for i in sorted(line, key=lambda i: i[1])) for line in lines
    ]

    # Length-weighted average: a confident 40-letter sentence should count
    # more than a doubtful 1-letter speck of dust.
    total_len = sum(len(i[3]) for i in items)
    weighted = sum(len(i[3]) * i[4] for i in items) / total_len

    return OcrResult(
        text="\n".join(text_lines),
        confidence=round(weighted, 4),
        box_count=len(items),
    )


# --------------------------------------------------------------------------
# The real EasyOCR engine
# --------------------------------------------------------------------------
class EasyOcrEngine:
    """
    Lazily-created EasyOCR reader.

    Creating `easyocr.Reader` takes several seconds (it loads the neural
    networks into memory), so we create it ONCE, on first use, and reuse
    it. The lock stops two threads from creating it at the same time.
    """

    def __init__(self, languages: list[str], gpu: bool = False) -> None:
        self.languages = languages
        self.gpu = gpu
        self._reader = None
        self._lock = threading.Lock()

    def _get_reader(self):
        if self._reader is None:
            with self._lock:
                if self._reader is None:  # check again inside the lock
                    try:
                        # Imported here, not at the top of the file, so the
                        # rest of the app (and the tests) work even when
                        # easyocr/PyTorch is not installed.
                        import easyocr
                    except ImportError as exc:
                        raise ExtractionError(
                            ExtractionErrorCode.OCR_UNAVAILABLE,
                            "EasyOCR is not installed. Run: pip install easyocr",
                        ) from exc
                    logger.info(
                        "Loading EasyOCR reader (languages=%s, gpu=%s)...",
                        self.languages,
                        self.gpu,
                    )
                    self._reader = easyocr.Reader(
                        self.languages, gpu=self.gpu, verbose=False
                    )
        return self._reader

    def read_image(self, image_png: bytes) -> OcrResult:
        reader = self._get_reader()
        try:
            # detail=1 -> return boxes + confidence (not just strings)
            # paragraph=False -> keep individual boxes so we get confidences
            detections = reader.readtext(image_png, detail=1, paragraph=False)
        except Exception as exc:
            raise ExtractionError(
                ExtractionErrorCode.OCR_FAILED,
                "EasyOCR failed while reading the page image.",
                details={"reason": str(exc)},
            ) from exc
        return detections_to_result(detections)


# One shared engine per (languages, gpu) combination for the whole process.
_engines: dict[tuple[tuple[str, ...], bool], EasyOcrEngine] = {}
_engines_lock = threading.Lock()


def get_default_ocr_engine(languages: list[str], gpu: bool) -> EasyOcrEngine:
    key = (tuple(languages), gpu)
    with _engines_lock:
        if key not in _engines:
            _engines[key] = EasyOcrEngine(list(languages), gpu)
        return _engines[key]
