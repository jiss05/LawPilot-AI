"""link chunks and ingestion jobs to documents; add pending source status

Revision ID: c4d8e2f1a7b3
Revises: 9abede709c56
Create Date: 2026-11-12 18:00:00

WHAT THIS MIGRATION CHANGES (and why)
-------------------------------------
1. document_chunks.knowledge_document_id  (new, required, FK)
   Chunks used to point only to the EDITION (source_version_id). If one
   edition ever had two files, both would have a "chunk 0" and break the
   unique rule. Now every chunk records exactly which FILE it came from.
   The unique rule moves from (source_version_id, chunk_index) to
   (knowledge_document_id, chunk_index).

2. ingestion_jobs.knowledge_document_id  (new, optional, FK)
   The job log can now say which file it processed, instead of hiding the
   id inside the `counts` JSON. Optional (NULL allowed) because a future
   job might process a whole source, not one file.

3. source_versions.status may now be 'pending'
   A newly uploaded edition is 'pending' until processing has finished;
   before this, the only allowed words forced it to be 'active' too early.

4. Storage keys no longer start with "legal_documents/"
   Upload and extraction now share one storage folder setting, and keys
   are relative to it. Existing rows are rewritten so old uploads still
   resolve to the same file.

Run with:   alembic upgrade head
Undo with:  alembic downgrade -1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d8e2f1a7b3"
down_revision: Union[str, Sequence[str], None] = "9abede709c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = "'active', 'superseded', 'withdrawn', 'failed'"
NEW_STATUSES = "'pending', 'active', 'superseded', 'withdrawn', 'failed'"


def upgrade() -> None:
    # ---- 1. chunks -> document --------------------------------------------
    # NOT NULL works because no chunks exist before this story. If your
    # database somehow has chunk rows, delete them first (they would be
    # re-created by running the chunking step again).
    op.add_column(
        "document_chunks",
        sa.Column("knowledge_document_id", sa.UUID(), nullable=False),
    )
    op.create_foreign_key(
        "fk_document_chunks_knowledge_document",
        "document_chunks",
        "knowledge_documents",
        ["knowledge_document_id"],
        ["id"],
        # Deleting a document row deletes its chunks automatically.
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_document_chunks_version_index", "document_chunks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_document_chunks_document_index",
        "document_chunks",
        ["knowledge_document_id", "chunk_index"],
    )
    # The unique constraint above also works as an index for
    # "WHERE knowledge_document_id = ..." look-ups, so no extra index.

    # ---- 2. jobs -> document ----------------------------------------------
    op.add_column(
        "ingestion_jobs",
        sa.Column("knowledge_document_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_knowledge_document",
        "ingestion_jobs",
        "knowledge_documents",
        ["knowledge_document_id"],
        ["id"],
        # Keep the job history even if the document is deleted.
        ondelete="SET NULL",
    )
    # PostgreSQL does NOT index foreign keys automatically; the admin
    # dashboard will often ask "jobs for this document" and "failed jobs".
    op.create_index(
        "idx_ingestion_jobs_document", "ingestion_jobs", ["knowledge_document_id"]
    )
    op.create_index("idx_ingestion_jobs_status", "ingestion_jobs", ["status"])
    # Back-fill the new column for jobs recorded before this migration.
    op.execute(
        """
        UPDATE ingestion_jobs
        SET knowledge_document_id = (counts->>'document_id')::uuid
        WHERE knowledge_document_id IS NULL
          AND counts ? 'document_id'
          AND EXISTS (
              SELECT 1 FROM knowledge_documents d
              WHERE d.id = (ingestion_jobs.counts->>'document_id')::uuid
          )
        """
    )

    # ---- 3. allow 'pending' on source_versions ----------------------------
    op.drop_constraint("ck_source_versions_status", "source_versions", type_="check")
    op.create_check_constraint(
        "ck_source_versions_status", "source_versions", f"status IN ({NEW_STATUSES})"
    )

    # ---- 4. storage keys relative to the storage folder -------------------
    for table, column in (
        ("knowledge_documents", "storage_key"),
        ("source_versions", "raw_storage_key"),
    ):
        op.execute(
            f"""
            UPDATE {table}
            SET {column} = substr({column}, length('legal_documents/') + 1)
            WHERE {column} LIKE 'legal_documents/%'
            """
        )


def downgrade() -> None:
    for table, column in (
        ("knowledge_documents", "storage_key"),
        ("source_versions", "raw_storage_key"),
    ):
        op.execute(
            f"""
            UPDATE {table}
            SET {column} = 'legal_documents/' || {column}
            WHERE {column} IS NOT NULL AND {column} NOT LIKE 'legal_documents/%'
            """
        )

    # 'pending' rows would break the old rule, so turn them back into 'active'.
    op.execute("UPDATE source_versions SET status = 'active' WHERE status = 'pending'")
    op.drop_constraint("ck_source_versions_status", "source_versions", type_="check")
    op.create_check_constraint(
        "ck_source_versions_status", "source_versions", f"status IN ({OLD_STATUSES})"
    )

    op.drop_index("idx_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_document", table_name="ingestion_jobs")
    op.drop_constraint(
        "fk_ingestion_jobs_knowledge_document", "ingestion_jobs", type_="foreignkey"
    )
    op.drop_column("ingestion_jobs", "knowledge_document_id")

    op.drop_constraint(
        "uq_document_chunks_document_index", "document_chunks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_document_chunks_version_index",
        "document_chunks",
        ["source_version_id", "chunk_index"],
    )
    op.drop_constraint(
        "fk_document_chunks_knowledge_document", "document_chunks", type_="foreignkey"
    )
    op.drop_column("document_chunks", "knowledge_document_id")
