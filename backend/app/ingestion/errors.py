"""
Error codes for document extraction.

WHY ERROR CODES INSTEAD OF PLAIN EXCEPTIONS?
--------------------------------------------
Acceptance criteria: "Extraction failures are recorded" and "Empty or
corrupted documents are identified".

A stable, machine-readable code (e.g. `CORRUPTED_FILE`) lets us:
  * store it in `ingestion_jobs.error_summary` / `counts`,
  * map it to a clear `knowledge_documents.processing_status`,
  * later show/filter it in the admin dashboard,
  * write tests that check the exact reason a file was rejected.

The human-readable `message` is for people; the `code` is for programs.
"""

from enum import Enum
from typing import Any


class ExtractionErrorCode(str, Enum):
    # Inheriting from `str` makes each member behave like a normal string,
    # so it can be saved straight into JSON / the database.

    # --- problems with the file itself (validation) ---
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    EMPTY_FILE = "EMPTY_FILE"                  # 0-byte file
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"  # e.g. .xlsx, .exe
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"  # e.g. a .txt renamed to .pdf
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"    # file changed since upload
    CORRUPTED_FILE = "CORRUPTED_FILE"          # the parser cannot open it
    ENCRYPTED_FILE = "ENCRYPTED_FILE"          # password-protected PDF
    TOO_MANY_PAGES = "TOO_MANY_PAGES"

    # --- problems with the content ---
    NO_TEXT_FOUND = "NO_TEXT_FOUND"            # opened fine but nothing to read

    # --- OCR problems ---
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"        # easyocr not installed / disabled
    OCR_FAILED = "OCR_FAILED"

    # --- anything we did not expect (a bug or an environment problem) ---
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


# Groups used by the pipeline to decide which status a document gets.
EMPTY_ERROR_CODES = frozenset(
    {ExtractionErrorCode.EMPTY_FILE, ExtractionErrorCode.NO_TEXT_FOUND}
)
CORRUPTED_ERROR_CODES = frozenset(
    {
        ExtractionErrorCode.CORRUPTED_FILE,
        ExtractionErrorCode.SIGNATURE_MISMATCH,
        ExtractionErrorCode.CHECKSUM_MISMATCH,
        ExtractionErrorCode.ENCRYPTED_FILE,
    }
)


class ExtractionError(Exception):
    """
    Raised whenever a document cannot be extracted.

    Example:
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The PDF could not be opened.",
            details={"reason": "xref table broken"},
        )
    """

    def __init__(
        self,
        code: ExtractionErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # Extra facts that help debugging (never put document text here,
        # BRD §12: "minimize logs").
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Shape stored in `ingestion_jobs.counts["error"]`."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"
