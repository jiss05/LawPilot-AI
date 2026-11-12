"""
Data structures returned by text extraction.

THE KEY IDEA: KEEP TEXT PAGE BY PAGE
------------------------------------
Acceptance criterion: "Page references are preserved where available."

If we joined the whole document into one long string, we would lose the
page each sentence came from, and later the agents could not cite
"Indian Contract Act, page 12". So extraction returns a list of `PageText`
objects, one per page, and the chunker (next story) copies `page_number`
into `document_chunks.page_number`.

"Where available" matters:
  * PDF and scanned images have real pages        -> page_number = 1, 2, 3 ...
  * DOCX has no fixed pages (Word lays them out at
    display time); we use page breaks if present  -> page_number = 1, 2 ...
                                                     with a warning that they
                                                     are approximate
  * TXT has no pages unless it contains form-feed
    characters ("\f")                             -> page_number = None

We use `dataclasses` (like the RAG branch does in `app/rag/types.py`):
they are plain Python objects with no database dependency, so they are
easy to test and to save as JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ExtractionMethod(str, Enum):
    """How the text of one page was obtained."""

    NATIVE = "native"  # text was stored in the file (selectable text)
    OCR = "ocr"        # text was read from an image of the page
    NONE = "none"      # nothing could be read (blank page, failure)


class FileType(str, Enum):
    """Formats this story supports (BRD §3.1: PDF, DOCX, TXT, scanned docs)."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"

    @property
    def is_image(self) -> bool:
        return self in {FileType.PNG, FileType.JPEG, FileType.TIFF}


@dataclass
class PageText:
    """Text of a single page (or a single section for page-less formats)."""

    # 1-based page number, or None when the format has no pages.
    page_number: int | None
    text: str
    method: ExtractionMethod
    # Average EasyOCR confidence 0..1 (only for OCR pages).
    ocr_confidence: float | None = None
    # Short machine-readable notes, e.g. "low_ocr_confidence", "blank_page".
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        # Count only non-whitespace characters, so a page full of spaces
        # and newlines is still treated as empty.
        return sum(1 for ch in self.text if not ch.isspace())

    @property
    def is_empty(self) -> bool:
        return self.char_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["method"] = self.method.value
        data["char_count"] = self.char_count
        return data


@dataclass
class ExtractionResult:
    """Everything extraction learned about one document."""

    file_type: FileType
    pages: list[PageText]
    # True when page numbers come from the file itself (PDF, images).
    # False when they are estimated (DOCX page breaks) or missing (TXT).
    page_numbers_reliable: bool = True
    # Document-level warnings (page-level ones live on each PageText).
    warnings: list[str] = field(default_factory=list)

    # ------------- convenience properties used by the pipeline ----------
    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_chars(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def is_empty(self) -> bool:
        return self.total_chars == 0

    @property
    def full_text(self) -> str:
        """All text joined together (handy for debugging / hashing)."""
        return "\n\n".join(page.text for page in self.pages if page.text)

    def count_by_method(self, method: ExtractionMethod) -> int:
        return sum(1 for page in self.pages if page.method == method)

    def summary(self) -> dict[str, Any]:
        """
        Small statistics dictionary saved in `ingestion_jobs.counts`.
        It contains NO document text, only numbers (BRD §12: minimize logs).
        """
        ocr_confidences = [
            p.ocr_confidence for p in self.pages if p.ocr_confidence is not None
        ]
        return {
            "file_type": self.file_type.value,
            "pages_total": self.page_count,
            "pages_native": self.count_by_method(ExtractionMethod.NATIVE),
            "pages_ocr": self.count_by_method(ExtractionMethod.OCR),
            "pages_empty": sum(1 for p in self.pages if p.is_empty),
            "total_chars": self.total_chars,
            "avg_ocr_confidence": (
                round(sum(ocr_confidences) / len(ocr_confidences), 3)
                if ocr_confidences
                else None
            ),
            "page_numbers_reliable": self.page_numbers_reliable,
            "warnings": sorted(
                set(self.warnings)
                | {w for p in self.pages for w in p.warnings}
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full JSON-ready representation (saved to the extracted/ folder)."""
        return {
            "file_type": self.file_type.value,
            "page_numbers_reliable": self.page_numbers_reliable,
            "warnings": list(self.warnings),
            "summary": self.summary(),
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionResult":
        """Rebuild a result from saved JSON (the chunker will use this)."""
        pages = [
            PageText(
                page_number=p["page_number"],
                text=p["text"],
                method=ExtractionMethod(p["method"]),
                ocr_confidence=p.get("ocr_confidence"),
                warnings=list(p.get("warnings", [])),
            )
            for p in data["pages"]
        ]
        return cls(
            file_type=FileType(data["file_type"]),
            pages=pages,
            page_numbers_reliable=data.get("page_numbers_reliable", True),
            warnings=list(data.get("warnings", [])),
        )
