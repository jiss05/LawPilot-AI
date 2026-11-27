"""
Load the stored record of cited chunks from PostgreSQL (SCRUM-26).

Used when the citations to check did not come from this request's
retrieval, e.g. a draft a lawyer edited days later. A chunk the caller is
not allowed to see is treated exactly like a missing one, so verification
never reveals that a private document exists.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.rag.sources import build_citation
from app.rag.store_retriever import INTERNAL_ROLES, _hydrate
from app.rag.types import ACTIVE_VERSION_STATUS, READY_PROCESSING_STATUSES


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _visible(row, user_id: UUID | None, roles: frozenset[str]) -> bool:
    if "admin" in roles:
        return True
    if row.visibility == "public":
        return True
    if row.visibility == "internal":
        return bool(roles & INTERNAL_ROLES)
    if row.visibility == "private":
        return user_id is not None and row.uploaded_by == user_id
    return False


def load_stored_sources(
    db: Session,
    chunk_ids: Iterable[Any],
    *,
    user_id: UUID | None = None,
    roles: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    ids = [u for u in (_as_uuid(c) for c in chunk_ids) if u is not None]
    if not ids:
        return {}
    role_set = frozenset(str(r).lower() for r in roles)
    out: dict[str, dict[str, Any]] = {}
    for chunk_id, row in _hydrate(db, list(dict.fromkeys(ids))).items():
        if not _visible(row, user_id, role_set):
            continue
        out[str(chunk_id)] = {
            "text": row.text or "",
            "source_title": row.title,
            "citation": build_citation(row.page_number, row.section_ref),
            "section_ref": row.section_ref,
            "page_number": row.page_number,
            "active": (
                row.version_status == ACTIVE_VERSION_STATUS
                and row.processing_status in READY_PROCESSING_STATUSES
            ),
        }
    return out
