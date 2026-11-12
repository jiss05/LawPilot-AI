"""
Local file storage helpers.

There is no object storage (S3/MinIO) in the project yet, so documents
live in a local folder (`INGESTION_STORAGE_DIR`, default
`backend/storage/documents`). `knowledge_documents.storage_key` holds a
path RELATIVE to that folder, so the folder can move without changing
database rows. A later story can swap this module for S3 without touching
the extractor.

SECURITY: PATH TRAVERSAL
------------------------
If a storage_key were "../../.env", joining it to the storage folder would
point OUTSIDE the folder and could expose secrets. `resolve_storage_path`
resolves the final absolute path and refuses anything that escapes the
storage folder (BRD §12: treat inputs as untrusted).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from app.ingestion.config import IngestionSettings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import ExtractionResult


def resolve_storage_path(storage_key: str, settings: IngestionSettings) -> Path:
    root = settings.storage_dir.resolve()
    candidate = (root / storage_key).resolve()
    # `is_relative_to` is True only if `candidate` is inside `root`.
    if Path(storage_key).is_absolute() or not candidate.is_relative_to(root):
        raise ExtractionError(
            ExtractionErrorCode.FILE_NOT_FOUND,
            "Invalid storage key: it points outside the document storage folder.",
            details={"storage_key": storage_key},
        )
    return candidate


def extraction_output_path(document_id: UUID, settings: IngestionSettings) -> Path:
    return settings.extracted_dir / f"{document_id}.extracted.json"


def save_extraction_result(
    document_id: UUID,
    result: ExtractionResult,
    settings: IngestionSettings,
) -> Path:
    """
    Save the page-by-page result as JSON and return its path.

    "Atomic" write: we write to a temporary file first, then rename it.
    A rename is all-or-nothing, so a crash half-way can never leave a
    half-written JSON file that the chunker would later fail to read.
    """
    output_path = extraction_output_path(document_id, settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # ensure_ascii=False keeps Hindi / "§" readable in the file.
            json.dump(
                {"document_id": str(document_id), **result.to_dict()},
                handle,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(tmp_name, output_path)  # works on Windows too
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return output_path


def load_extraction_result(document_id: UUID, settings: IngestionSettings) -> ExtractionResult:
    """Read a saved result back (the chunking story will call this)."""
    path = extraction_output_path(document_id, settings)
    with path.open(encoding="utf-8") as handle:
        return ExtractionResult.from_dict(json.load(handle))
