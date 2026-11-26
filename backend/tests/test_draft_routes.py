
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies import get_current_user
from app.db.session import get_db
from fastapi import HTTPException

from app.api import draft_routes
from datetime import datetime, timezone

def make_mock_user(role: str):
    """Create a mock user with one assigned application role."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_active=True,
        role_assignments=[
            SimpleNamespace(
                role=SimpleNamespace(code=role)
            )
        ],
    )


@pytest.fixture
def client():
    """Create a test client without connecting to PostgreSQL."""

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "role",
    ["CLIENT", "JUDGE", "ADMIN"],
)
@pytest.mark.parametrize(
    "method,endpoint,payload",
    [
        (
            "post",
            "/api/v1/drafts/generate",
            {
                "matter_id": str(uuid.uuid4()),
                "title": "Test Draft",
                "document_type": "Legal Notice",
                "case_facts": "A sufficiently detailed description of the legal dispute.",
            },
        ),
        (
            "put",
            f"/api/v1/drafts/{uuid.uuid4()}",
            {
                "title": "Updated Draft",
                "content": "Updated legal content.",
            },
        ),
        (
            "post",
            f"/api/v1/drafts/{uuid.uuid4()}/review",
            None,
        ),
        (
            "post",
            f"/api/v1/drafts/{uuid.uuid4()}/export",
            None,
        ),
    ],
)
def test_non_lawyer_cannot_manage_drafts(
    client,
    role,
    method,
    endpoint,
    payload,
):
    """Only LAWYER users can generate, edit, review, or export drafts."""

    app.dependency_overrides[get_current_user] = (
        lambda: make_mock_user(role)
    )

    response = getattr(client, method)(
        endpoint,
        json=payload,
    ) if payload is not None else getattr(client, method)(endpoint)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Only lawyers can perform this action."
    )



def test_matter_owner_has_implicit_access():
    """Matter owners do not need a separate membership record."""

    user_id = uuid.uuid4()
    matter = SimpleNamespace(
        id=uuid.uuid4(),
        owner_user_id=user_id,
    )
    user = SimpleNamespace(id=user_id)

    class FakeDB:
        def scalar(self, query):
            raise AssertionError("Membership lookup should not be needed.")

    draft_routes._matter_access(
        FakeDB(),
        matter,
        user,
        write=True,
    )


def test_member_with_read_permission_cannot_write():
    """Read-only members cannot generate drafts."""

    user_id = uuid.uuid4()
    matter = SimpleNamespace(
        id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
    )
    user = SimpleNamespace(id=user_id)

    class FakeDB:
        def scalar(self, query):
            return SimpleNamespace(permission="read")

    with pytest.raises(HTTPException) as error:
        draft_routes._matter_access(
            FakeDB(),
            matter,
            user,
            write=True,
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Write permission is required for this matter."


def test_member_with_write_permission_can_write():
    """Members with write permission can generate drafts."""

    user_id = uuid.uuid4()
    matter = SimpleNamespace(
        id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
    )
    user = SimpleNamespace(id=user_id)

    class FakeDB:
        def scalar(self, query):
            return SimpleNamespace(permission="write")

    draft_routes._matter_access(
        FakeDB(),
        matter,
        user,
        write=True,
    )


def test_non_member_cannot_access_matter():
    """Users without matter membership cannot access another matter."""

    matter = SimpleNamespace(
        id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
    )
    user = SimpleNamespace(id=uuid.uuid4())

    class FakeDB:
        def scalar(self, query):
            return None

    with pytest.raises(HTTPException) as error:
        draft_routes._matter_access(
            FakeDB(),
            matter,
            user,
        )

    assert error.value.status_code == 404


def test_only_draft_owner_can_modify():
    """Another lawyer cannot modify the draft owner's document."""

    owner = SimpleNamespace(id=uuid.uuid4())
    another_lawyer = SimpleNamespace(id=uuid.uuid4())
    draft = SimpleNamespace(owner_user_id=owner.id)

    with pytest.raises(HTTPException) as error:
        draft_routes._require_draft_owner(
            draft,
            another_lawyer,
        )

    assert error.value.status_code == 403


def test_draft_owner_can_modify():
    """The lawyer who created the draft can modify it."""

    owner = SimpleNamespace(id=uuid.uuid4())
    draft = SimpleNamespace(owner_user_id=owner.id)

    draft_routes._require_draft_owner(draft, owner)



def make_mock_draft(owner_id, status="draft"):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=uuid.uuid4(),
        matter_id=uuid.uuid4(),
        owner_user_id=owner_id,
        title="Legal Notice",
        content="Original legal draft content.",
        citations=[
            {
                "source_title": "Indian Contract Act",
                "citation": "Section 73",
                "url": "https://example.org/contract-act",
            }
        ],
        status=status,
        version=1,
        reviewed_at=None,
        exported_at=None,
        created_at=now,
        updated_at=now,
    )


class FakeDraftDB:
    def __init__(self, draft):
        self.draft = draft
        self.added = []

    def get(self, model, record_id):
        return self.draft

    def add(self, record):
        self.added.append(record)

    def commit(self):
        pass

    def refresh(self, record):
        pass


def setup_draft_test(client, monkeypatch, draft, user):
    fake_db = FakeDraftDB(draft)

    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    monkeypatch.setattr(
        draft_routes,
        "record_audit",
        lambda *args, **kwargs: None,
    )

    return fake_db


def test_editing_draft_increments_version_and_resets_review(
    client,
    monkeypatch,
):
    user = make_mock_user("LAWYER")
    draft = make_mock_draft(user.id)
    draft.status = "reviewed"
    draft.reviewed_at = datetime.now(timezone.utc)

    fake_db = setup_draft_test(client, monkeypatch, draft, user)

    response = client.put(
        f"/api/v1/drafts/{draft.id}",
        json={
            "title": "Updated Legal Notice",
            "content": "Updated legal draft content.",
        },
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["status"] == "draft"
    assert response.json()["reviewed_at"] is None

    assert draft.title == "Updated Legal Notice"
    assert draft.content == "Updated legal draft content."

    assert len(fake_db.added) == 1
    assert fake_db.added[0].version == 2


def test_export_before_self_review_is_rejected(
    client,
    monkeypatch,
):
    user = make_mock_user("LAWYER")
    draft = make_mock_draft(user.id)

    setup_draft_test(client, monkeypatch, draft, user)

    response = client.post(
        f"/api/v1/drafts/{draft.id}/export"
    )

    assert response.status_code == 409
    assert "Review the draft yourself" in response.json()["detail"]


def test_self_review_changes_draft_status(
    client,
    monkeypatch,
):
    user = make_mock_user("LAWYER")
    draft = make_mock_draft(user.id)

    setup_draft_test(client, monkeypatch, draft, user)

    response = client.post(
        f"/api/v1/drafts/{draft.id}/review"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"
    assert response.json()["reviewed_at"] is not None

    assert draft.status == "reviewed"
    assert draft.reviewed_at is not None


def test_exported_draft_cannot_be_edited(
    client,
    monkeypatch,
):
    user = make_mock_user("LAWYER")
    draft = make_mock_draft(user.id, status="exported")
    draft.exported_at = datetime.now(timezone.utc)

    setup_draft_test(client, monkeypatch, draft, user)

    response = client.put(
        f"/api/v1/drafts/{draft.id}",
        json={
            "title": "Attempted Edit",
            "content": "This edit should be rejected.",
        },
    )

    assert response.status_code == 409
    assert "cannot be edited" in response.json()["detail"]



def test_reviewed_draft_exports_as_word_document(
    client,
    monkeypatch,
):
    from io import BytesIO
    from docx import Document

    user = make_mock_user("LAWYER")
    draft = make_mock_draft(user.id, status="reviewed")
    draft.reviewed_at = datetime.now(timezone.utc)

    setup_draft_test(client, monkeypatch, draft, user)

    response = client.post(
        f"/api/v1/drafts/{draft.id}/export"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert ".docx" in response.headers["content-disposition"]

    document = Document(BytesIO(response.content))

    paragraphs = [p.text for p in document.paragraphs]

    assert "Legal Notice" in paragraphs
    assert "DRAFT - Requires professional verification" in paragraphs
    assert "Original legal draft content." in paragraphs
    assert any(
        "Indian Contract Act" in paragraph
        for paragraph in paragraphs
    )
    assert draft.status == "exported"
    assert draft.exported_at is not None
