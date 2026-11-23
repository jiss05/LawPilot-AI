"""
Export the chunks of one uploaded document to a readable text file.

WHY: after an upload, the chunks live in the database (table
document_chunks) and in Qdrant. Neither is easy to read. This script
writes them out as a plain .txt file you can open in VS Code or share
with the team.

Where the data of an upload lives (document_id = the id from the upload):

    1. Original file   backend/legal_documents/<document_id>.pdf
    2. Page text       backend/storage/extracted/<document_id>.extracted.json
    3. Chunks          PostgreSQL table  document_chunks   (this script reads it)
    4. Vectors         Qdrant collection legal_chunks_v1   (one point per chunk,
                       point id = chunk id)

HOW TO RUN (from the backend folder, virtual environment active):

    # chunks that are saved in the database
    python scripts/export_chunks.py <document_id>

    # preview: re-chunk the extracted JSON WITHOUT touching the database
    # (useful to compare the current chunker with what is stored)
    python scripts/export_chunks.py <document_id> --from-json

The file is written to backend/storage/exports/<document_id>.chunks.txt
(use --out to choose another path).
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))  # so "import app..." works when run as a script

LINE = "=" * 78


def _format_chunk(index, section, page_start, page_end, tokens, part, parts, text, footnotes) -> str:
    """One chunk as a readable block of text."""
    pages = f"{page_start}" if page_start == page_end or page_end is None else f"{page_start}-{page_end}"
    split = f"  |  part {part} of {parts}" if parts and parts > 1 else ""
    lines = [
        LINE,
        f"CHUNK {index}  |  {section or '(no section)'}  |  page {pages}  |  {tokens} tokens{split}",
        LINE,
        text.strip(),
    ]
    if footnotes:
        lines += ["", "  Amendment footnotes on these pages:"]
        lines += [textwrap.fill(n, 76, initial_indent="    ", subsequent_indent="      ") for n in footnotes]
    return "\n".join(lines) + "\n\n"


def _header(title: str, document_id: str, count: int, origin: str) -> str:
    return (
        f"{title}\n"
        f"Document id : {document_id}\n"
        f"Chunks      : {count}\n"
        f"Read from   : {origin}\n\n"
    )


def export_from_database(document_id: uuid.UUID) -> str:
    """Read the saved chunks from PostgreSQL (table document_chunks)."""
    from sqlalchemy import select

    import app.models  # noqa: F401  (registers all models)
    from app.db.session import SessionLocal
    from app.models.document_chunk import DocumentChunk
    from app.models.knowledge_document import KnowledgeDocument

    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise SystemExit(f"No document with id {document_id} in the database.")
        rows = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.knowledge_document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        if not rows:
            raise SystemExit(f"Document {document_id} has no chunks yet (status: {document.status}).")

        meta0 = rows[0].chunk_metadata or {}
        title = meta0.get("source_title") or getattr(document, "original_filename", "") or "Document"
        out = _header(title, str(document_id), len(rows),
                      f"PostgreSQL table document_chunks (chunker version {meta0.get('chunker_version', '?')})")
        for row in rows:
            meta = row.chunk_metadata or {}
            out += _format_chunk(row.chunk_index, row.section_ref, row.page_number, meta.get("page_end"),
                                 row.token_count, meta.get("part"), meta.get("parts"), row.text,
                                 meta.get("footnotes", []))
        return out


def export_from_json(document_id: str) -> str:
    """Re-chunk the saved page text with the CURRENT chunker (database not used)."""
    from app.ingestion.chunking import chunk_document
    from app.ingestion.chunking.chunker import CHUNKER_VERSION
    from app.ingestion.chunking.structure import Mode
    from app.ingestion.extraction_types import ExtractionResult

    path = BACKEND_DIR / "storage" / "extracted" / f"{document_id}.extracted.json"
    if not path.exists():
        raise SystemExit(f"Not found: {path}")
    result = ExtractionResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    chunking = chunk_document(result, Mode.STATUTE)
    out = _header("Preview (re-chunked from the extracted JSON)", document_id, len(chunking.chunks),
                  f"{path.name} with chunker version {CHUNKER_VERSION}")
    for chunk in chunking.chunks:
        out += _format_chunk(chunk.chunk_index, chunk.section_ref, chunk.page_start, chunk.page_end,
                             chunk.token_count, chunk.part, chunk.parts, chunk.text,
                             chunking.footnotes_for(chunk))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the chunks of one document to a .txt file.")
    parser.add_argument("document_id", help="id of the uploaded document (knowledge_documents.id)")
    parser.add_argument("--from-json", action="store_true",
                        help="re-chunk storage/extracted/<id>.extracted.json instead of reading the database")
    parser.add_argument("--out", type=Path, help="output file (default: storage/exports/<id>.chunks.txt)")
    args = parser.parse_args()

    try:
        document_id = uuid.UUID(args.document_id)
    except ValueError:
        raise SystemExit(f"Not a valid document id: {args.document_id}")

    text = export_from_json(str(document_id)) if args.from_json else export_from_database(document_id)
    out = args.out or BACKEND_DIR / "storage" / "exports" / f"{document_id}.chunks.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
