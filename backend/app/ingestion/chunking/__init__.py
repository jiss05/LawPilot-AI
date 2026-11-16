"""
Cleaning and chunking of extracted legal text (Sprint 2 story:
"Implement document cleaning and chunking").

The three stages, each in its own file so each can be read and tested
on its own:

    cleaner.py    page text -> clean paragraphs (still page by page)
    structure.py  paragraphs -> labelled blocks (Chapter, Section 73, (1), (a), Para 12 ...)
    chunker.py    blocks -> chunks of a sensible size, with page + section references

`chunk_document()` runs all three. It needs no database; the database
step is in `app/ingestion/chunk_pipeline.py`.
"""

from app.ingestion.chunking.chunker import Chunk, ChunkingResult, chunk_document

__all__ = ["Chunk", "ChunkingResult", "chunk_document"]
