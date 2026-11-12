"""
LawPilot document ingestion package.

This story (Sprint 2) implements TEXT EXTRACTION + OCR, the first part of
the ingestion flow in BRD §5.2 / §10.1:

    validate file -> extract text -> OCR where needed -> record outcome
    (later stories: clean -> chunk -> embed -> index in Qdrant -> activate)

Main entry points:
    DocumentExtractor  (extractor.py) - file in, page-by-page text out
    run_extraction     (pipeline.py)  - same, plus database bookkeeping
    python -m app.ingestion.cli       - try it from the terminal

`run_extraction` is NOT imported here on purpose: it pulls in the
SQLAlchemy models, and the extractor should stay usable without them.
"""

from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extraction_types import (
    ExtractionMethod,
    ExtractionResult,
    FileType,
    PageText,
)
from app.ingestion.extractor import DocumentExtractor

__all__ = [
    "DocumentExtractor",
    "ExtractionError",
    "ExtractionErrorCode",
    "ExtractionMethod",
    "ExtractionResult",
    "FileType",
    "PageText",
]
