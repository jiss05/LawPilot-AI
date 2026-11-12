"""
File validation: run BEFORE any parser touches the file.

Acceptance criterion: "Empty or corrupted documents are identified."
BRD §10.1: "Validate the uploaded file type, MIME signature, file size,
document integrity ... Reject unsupported, corrupted, or unauthorized files."

WHAT IS A "SIGNATURE" (MAGIC BYTES)?
------------------------------------
Most binary formats start with fixed bytes that identify them:

    PDF   -> b"%PDF-"
    DOCX  -> b"PK\x03\x04"            (a DOCX is really a ZIP archive)
    PNG   -> b"\x89PNG\r\n\x1a\n"
    JPEG  -> b"\xff\xd8\xff"
    TIFF  -> b"II*\x00" or b"MM\x00*"

The file extension is just part of the name and anyone can change it.
Checking the first bytes tells us what the file REALLY is. If a file
called "judgment.pdf" does not start with "%PDF-", something is wrong
(renamed file, broken download, or something malicious), so we reject it.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from app.ingestion.config import IngestionSettings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import FileType

# Which extensions we accept and which type they claim to be.
EXTENSION_TO_TYPE: dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".txt": FileType.TXT,
    ".png": FileType.PNG,
    ".jpg": FileType.JPEG,
    ".jpeg": FileType.JPEG,
    ".tif": FileType.TIFF,
    ".tiff": FileType.TIFF,
}

# Magic bytes for each binary type. TXT has no signature (checked separately).
SIGNATURES: dict[FileType, tuple[bytes, ...]] = {
    FileType.PDF: (b"%PDF-",),
    FileType.DOCX: (b"PK\x03\x04",),
    FileType.PNG: (b"\x89PNG\r\n\x1a\n",),
    FileType.JPEG: (b"\xff\xd8\xff",),
    FileType.TIFF: (b"II*\x00", b"MM\x00*"),
}

# How many bytes from the start of the file we inspect.
HEADER_SIZE = 8192

# Byte-order marks that identify UTF-16 text files.
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """
    Return the SHA-256 hash of a file as 64 hex characters.

    We read the file in 1 MB pieces instead of all at once, so even a
    500 MB file uses very little memory.

    The upload story stores this value in `knowledge_documents.sha256`.
    Re-computing it before extraction proves the stored file has not been
    changed or damaged since it was uploaded.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_file_type(path: Path) -> FileType:
    """Return the file type claimed by the extension, or raise if unsupported."""
    suffix = path.suffix.lower()
    file_type = EXTENSION_TO_TYPE.get(suffix)
    if file_type is None:
        raise ExtractionError(
            ExtractionErrorCode.UNSUPPORTED_FORMAT,
            f"Files with extension '{suffix or '(none)'}' are not supported.",
            details={
                "extension": suffix,
                "supported": sorted(EXTENSION_TO_TYPE),
            },
        )
    return file_type


def _check_text_file(header: bytes) -> None:
    """
    A plain-text file has no magic bytes, so we use two simple rules:
      1. Text files almost never contain NUL bytes (b"\x00"); binary files
         (images, executables, PDFs) almost always do.
      2. It must not secretly be a known binary format.

    Exception: Windows Notepad's "Unicode" option saves UTF-16 text, which
    is full of NUL bytes but starts with a BOM (byte-order mark: FF FE or
    FE FF). We allow those; the TXT loader decodes them correctly.
    """
    if header.startswith(UTF16_BOMS):
        return
    if b"\x00" in header:
        raise ExtractionError(
            ExtractionErrorCode.SIGNATURE_MISMATCH,
            "File has a .txt extension but contains binary data.",
        )
    for file_type, signatures in SIGNATURES.items():
        if header.startswith(signatures):
            raise ExtractionError(
                ExtractionErrorCode.SIGNATURE_MISMATCH,
                f"File has a .txt extension but is actually a "
                f"{file_type.value.upper()} file.",
                details={"detected": file_type.value},
            )


def _check_docx_structure(path: Path) -> None:
    """
    A DOCX starts with "PK" like EVERY zip file (.xlsx, .pptx, .zip ...).
    A real Word document must contain the entry "word/document.xml".
    We also call `testzip()`, which verifies the CRC checksum of every
    entry and catches truncated or damaged files.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ExtractionError(
                    ExtractionErrorCode.SIGNATURE_MISMATCH,
                    "File is a ZIP archive but not a Word (.docx) document.",
                )
            broken_entry = archive.testzip()
            if broken_entry is not None:
                raise ExtractionError(
                    ExtractionErrorCode.CORRUPTED_FILE,
                    "The DOCX archive is damaged.",
                    details={"broken_entry": broken_entry},
                )
    except zipfile.BadZipFile as exc:
        raise ExtractionError(
            ExtractionErrorCode.CORRUPTED_FILE,
            "The DOCX file is not a valid ZIP archive (it may be truncated).",
            details={"reason": str(exc)},
        ) from exc


def validate_file(
    path: Path,
    settings: IngestionSettings,
    expected_sha256: str | None = None,
) -> FileType:
    """
    Run every pre-extraction check and return the verified file type.

    Checks, in order (cheapest first):
      1. the file exists
      2. it is not 0 bytes                    -> EMPTY_FILE
      3. it is not bigger than the limit      -> FILE_TOO_LARGE
      4. the extension is supported           -> UNSUPPORTED_FORMAT
      5. the magic bytes match the extension  -> SIGNATURE_MISMATCH
      6. DOCX only: ZIP structure is sound    -> CORRUPTED_FILE
      7. optional: SHA-256 matches the DB     -> CHECKSUM_MISMATCH

    Deeper corruption (e.g. a PDF with the right header but a broken body)
    is detected later, when the loader tries to open it.
    """
    path = Path(path)

    if not path.is_file():
        raise ExtractionError(
            ExtractionErrorCode.FILE_NOT_FOUND,
            "The stored document file could not be found.",
            details={"path": str(path)},
        )

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise ExtractionError(
            ExtractionErrorCode.EMPTY_FILE,
            "The document file is empty (0 bytes).",
        )

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ExtractionError(
            ExtractionErrorCode.FILE_TOO_LARGE,
            f"The file is larger than the {settings.max_file_size_mb} MB limit.",
            details={"size_bytes": size_bytes, "limit_bytes": max_bytes},
        )

    file_type = detect_file_type(path)

    with path.open("rb") as handle:
        header = handle.read(HEADER_SIZE)

    if file_type == FileType.TXT:
        _check_text_file(header)
    elif not header.startswith(SIGNATURES[file_type]):
        raise ExtractionError(
            ExtractionErrorCode.SIGNATURE_MISMATCH,
            f"The file content does not match its '{path.suffix}' extension.",
            details={"claimed": file_type.value, "header_hex": header[:8].hex()},
        )

    if file_type == FileType.DOCX:
        _check_docx_structure(path)

    if expected_sha256:
        actual = compute_sha256(path)
        if actual.lower() != expected_sha256.lower():
            raise ExtractionError(
                ExtractionErrorCode.CHECKSUM_MISMATCH,
                "The stored file does not match the checksum recorded at upload.",
                details={"expected": expected_sha256, "actual": actual},
            )

    return file_type
