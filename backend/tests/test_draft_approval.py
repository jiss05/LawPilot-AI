"""SCRUM-24: human review flag, authorized-reviewer approval, audited approval/export,
citation re-verification on edit and approval."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import draft_routes, matter_routes
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.draft_document import DraftDocument
from app.models.matter import Matter

STORED = {
    "chunk-1": {"text": "Section 73. Compensation for loss or damage caused by breach of contract.",
                "source_title": "Indian Contract Act", "citation": "Section 73",
                "section_ref": "Section 73", "page_number": 21, "active": True},
}


def lawyer(role="LAWYER"):
    return SimpleNamespace(id=uuid.uuid4(), is_active=True,
                           role_assignments=[SimpleNamespace(role=SimpleNamespace(code=role))])


def make_draft(owner_id, matter_id, status="reviewed", content="Compensation is payable [1]."):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(), matter_id=matter_id, owner_user_id=owner_id, title="Legal Notice",
        content=content,
        citations=[{"ref": 1, "chunk_id": "chunk-1", "source_title": "Indian Contract Act",
                    "citation": "Section 73"}],
        status=status, version=2, reviewed_at=now if status == "reviewed" else None,
        approved_by_user_id=None, approved_at=None, review_notes=None, exported_at=None,
        created_at=now, updated_at=now,
    )


class FakeDB:
    def __init__(self, draft, matter, member_permission=None):
        self.draft, self.matter, self.member_permission = draft, matter, member_permission
        self.added, self.commits = [], 0

    def get(self, model, record_id):
        return {DraftDocument: self.draft, Matter: self.matter}.get(model)

    def scalar(self, query):
        return SimpleNamespace(permission=self.member_permission) if self.member_permission else None

    def add(self, record):
        self.added.append(record)

    def commit(self):
        self.commits += 1

    def refresh(self, record):
        pass


@pytest.fixture
def env(monkeypatch):
    audits = []
    monkeypatch.setattr(draft_routes, "record_audit", lambda db, **kw: audits.append(kw))
    monkeypatch.setattr(draft_routes, "load_stored_sources", lambda db, ids, **kw: STORED)
    state = SimpleNamespace(audits=audits)

    def setup(user, draft, matter, member_permission=None):
        db = FakeDB(draft, matter, member_permission)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user
        return db

    state.setup = setup
    with TestClient(app) as client:
        state.client = client
        yield state
    app.dependency_overrides.clear()


def ids():
    author, matter_owner = lawyer(), lawyer()
    matter = SimpleNamespace(id=uuid.uuid4(), owner_user_id=matter_owner.id, status="active")
    return author, matter_owner, matter


def test_author_cannot_approve_own_draft(env):
    author, _, matter = ids()
    matter.owner_user_id = author.id
    draft = make_draft(author.id, matter.id)
    env.setup(author, draft, matter)
    r = env.client.post(f"/api/v1/drafts/{draft.id}/approve")
    assert r.status_code == 403
    assert draft.status == "reviewed"


def test_member_without_review_permission_cannot_approve(env):
    author, _, matter = ids()
    other = lawyer()
    draft = make_draft(author.id, matter.id)
    env.setup(other, draft, matter, member_permission="write")
    assert env.client.post(f"/api/v1/drafts/{draft.id}/approve").status_code == 403


def test_non_lawyer_cannot_approve(env):
    author, _, matter = ids()
    judge = lawyer("JUDGE")
    draft = make_draft(author.id, matter.id)
    env.setup(judge, draft, matter, member_permission="review")
    assert env.client.post(f"/api/v1/drafts/{draft.id}/approve").status_code == 403


@pytest.mark.parametrize("as_owner", [True, False])
def test_authorized_reviewer_approves_and_it_is_audited(env, as_owner):
    author, matter_owner, matter = ids()
    reviewer = matter_owner if as_owner else lawyer()
    draft = make_draft(author.id, matter.id)
    env.setup(reviewer, draft, matter, member_permission=None if as_owner else "review")

    r = env.client.post(f"/api/v1/drafts/{draft.id}/approve", json={"notes": "Looks right."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["requires_human_review"] is False
    assert body["approved_by_user_id"] == str(reviewer.id)
    assert body["review_notes"] == "Looks right."
    assert body["citations"][0]["verification_status"] == "verified"
    assert env.audits[-1]["action"] == "draft.approved"
    assert env.audits[-1]["actor_user_id"] == reviewer.id


def test_reviewer_sees_can_approve(env):
    author, matter_owner, matter = ids()
    draft = make_draft(author.id, matter.id)
    env.setup(matter_owner, draft, matter)
    assert env.client.get(f"/api/v1/drafts/{draft.id}").json()["can_approve"] is True
    env.setup(author, draft, matter)
    assert env.client.get(f"/api/v1/drafts/{draft.id}").json()["can_approve"] is False


def test_only_submitted_drafts_can_be_approved(env):
    author, matter_owner, matter = ids()
    draft = make_draft(author.id, matter.id, status="draft")
    env.setup(matter_owner, draft, matter)
    assert env.client.post(f"/api/v1/drafts/{draft.id}/approve").status_code == 409


def test_draft_with_failed_citations_cannot_be_approved(env):
    author, matter_owner, matter = ids()
    draft = make_draft(author.id, matter.id, content='The Act says "damages are tripled" [1] and [3].')
    env.setup(matter_owner, draft, matter)
    r = env.client.post(f"/api/v1/drafts/{draft.id}/approve")
    assert r.status_code == 409
    assert "could not be verified" in r.json()["detail"]
    assert draft.status == "reviewed"
    assert draft.citations[0]["verification_status"] == "failed"


def test_reviewer_can_request_changes(env):
    author, matter_owner, matter = ids()
    draft = make_draft(author.id, matter.id)
    env.setup(matter_owner, draft, matter)
    r = env.client.post(f"/api/v1/drafts/{draft.id}/request-changes", json={"notes": "Add the notice date."})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    assert r.json()["requires_human_review"] is True
    assert r.json()["review_notes"] == "Add the notice date."
    assert env.audits[-1]["action"] == "draft.changes_requested"


def test_generated_draft_requires_human_review(env):
    author, _, matter = ids()
    draft = make_draft(author.id, matter.id, status="draft")
    env.setup(author, draft, matter)
    body = env.client.get(f"/api/v1/drafts/{draft.id}").json()
    assert body["requires_human_review"] is True


def test_export_of_approved_draft_is_audited(env):
    author, _, matter = ids()
    draft = make_draft(author.id, matter.id, status="approved")
    draft.approved_at = datetime.now(timezone.utc)
    env.setup(author, draft, matter)
    r = env.client.post(f"/api/v1/drafts/{draft.id}/export")
    assert r.status_code == 200
    assert draft.status == "exported"
    assert env.audits[-1]["action"] == "draft.exported"


def test_edit_reverifies_citations_and_clears_approval(env):
    author, _, matter = ids()
    draft = make_draft(author.id, matter.id, status="approved")
    draft.approved_at = datetime.now(timezone.utc)
    env.setup(author, draft, matter)
    r = env.client.put(f"/api/v1/drafts/{draft.id}",
                       json={"title": "Legal Notice", "content": "Compensation [1]. Also see [5]."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft" and body["approved_at"] is None
    assert body["version"] == 3
    assert body["citations"][0]["verification_status"] == "verified"
    assert body["invalid_references"] == [5]
    assert body["citations_verified"] is False
    assert env.audits[-1]["action"] == "draft.updated"


# ------------------------------------------------------------------ matters
class FakeMatterDB:
    def __init__(self):
        self.added = []

    def add(self, record):
        record.id = record.id or uuid.uuid4()
        record.created_at = datetime.now(timezone.utc)
        self.added.append(record)

    def flush(self):
        pass

    def commit(self):
        pass

    def refresh(self, record):
        pass


def test_lawyer_creates_matter(monkeypatch):
    monkeypatch.setattr(matter_routes, "record_audit", lambda db, **kw: None)
    user = lawyer()
    app.dependency_overrides[get_db] = lambda: FakeMatterDB()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        r = client.post("/api/v1/matters", json={"title": "Kumar v. Singh", "court": "JMFC Kochi"})
    app.dependency_overrides.clear()
    assert r.status_code == 201, r.text
    assert r.json()["owner_user_id"] == str(user.id)
    assert r.json()["my_permission"] == "owner"


@pytest.mark.parametrize("role", ["CLIENT", "JUDGE"])
def test_non_lawyer_cannot_create_matter(role):
    app.dependency_overrides[get_db] = lambda: FakeMatterDB()
    app.dependency_overrides[get_current_user] = lambda: lawyer(role)
    with TestClient(app) as client:
        r = client.post("/api/v1/matters", json={"title": "X"})
    app.dependency_overrides.clear()
    assert r.status_code == 403
