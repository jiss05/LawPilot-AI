"""full-text search index on document_chunks.text

Revision ID: d7e3a91b5c20
Revises: c4d8e2f1a7b3
Create Date: 2026-11-16 12:00:00

WHY (SCRUM-16, hybrid retrieval)
--------------------------------
Keyword search runs inside PostgreSQL using its built-in full-text search:
  * to_tsvector('english', text) turns a chunk into searchable word stems
    ("compensation", "compensated" -> "compens"), dropping words like "the".
  * A GIN index on that expression makes "which chunks contain these
    words?" fast even with millions of chunks, like the index at the back
    of a book.
The keyword query in app/rag/store_retriever.py uses exactly the same
expression, which is what lets PostgreSQL use this index.

Also indexes the columns the retriever joins and filters on.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d7e3a91b5c20"
down_revision: Union[str, Sequence[str], None] = "c4d8e2f1a7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_fts "
        "ON document_chunks USING GIN (to_tsvector('english', text))"
    )
    op.create_index("idx_knowledge_documents_version", "knowledge_documents", ["source_version_id"])
    op.create_index("idx_knowledge_documents_status", "knowledge_documents", ["processing_status"])
    op.create_index("idx_source_versions_source", "source_versions", ["source_id"])


def downgrade() -> None:
    op.drop_index("idx_source_versions_source", table_name="source_versions")
    op.drop_index("idx_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("idx_knowledge_documents_version", table_name="knowledge_documents")
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_fts")
