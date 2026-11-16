"""
Audit trail helper (SCRUM-18: "Administrative operations are traceable").

Every administrative action on the knowledge base writes one row to
`audit_events`: WHO (actor_user_id) did WHAT (action) to WHICH object
(target_type + target_id), WHEN (occurred_at) and in WHICH HTTP request
(request_id, also returned to the caller in the X-Request-ID header).

Actions recorded:
    knowledge_source.created      upload of a new source (first edition)
    source_version.created        upload of a new edition of a source
    source_version.activated      edition made searchable (automatic or manual)
    source_version.superseded     older edition replaced by a newer one
    source_version.withdrawn      edition removed from search by an admin
    document.reprocess_requested  admin asked to re-run the pipeline

BRD §12: "Minimize logs". The metadata holds identifiers and short reasons,
never document text or personal details.

The helper only ADDS the row to the session; the caller commits it together
with the change it describes, so the action and its audit record are saved
(or rolled back) together.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


def record_audit(
    db: Session,
    *,
    actor_user_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID | str | None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        request_id=request_id,
        metadata_json=metadata or {},
    )
    db.add(event)
    return event
