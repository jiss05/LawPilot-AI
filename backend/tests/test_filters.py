"""Acceptance: metadata and authorization filters applied before return."""

from __future__ import annotations

from uuid import uuid4

from tests.conftest import make_chunk

from app.rag.filters import (
    apply_access_filters,
    apply_metadata_filters,
    filter_indexed_corpus,
    filter_search_hits,
    is_authorized,
)
from app.rag.ranking import hit_from_indexed
from app.rag.types import (
    VISIBILITY_INTERNAL,
    VISIBILITY_MATTER,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    AccessContext,
    MetadataFilters,
)


def test_metadata_filter_by_jurisdiction(sample_corpus):
    filters = MetadataFilters(jurisdictions=frozenset({"USA-CA"}))
    kept = apply_metadata_filters(sample_corpus, filters)
    assert len(kept) == 1
    assert kept[0].jurisdiction == "USA-CA"


def test_metadata_filter_by_trust_tier_and_source_type(sample_corpus):
    filters = MetadataFilters(
        trust_tiers=frozenset({"secondary"}),
        source_types=frozenset({"treatise"}),
    )
    kept = apply_metadata_filters(sample_corpus, filters)
    assert len(kept) == 1
    assert "tort" in kept[0].text.lower()


def test_metadata_equals_on_custom_fields():
    chunks = [
        make_chunk(text="A", metadata={"court": "Supreme Court"}),
        make_chunk(text="B", metadata={"court": "High Court"}),
    ]
    filters = MetadataFilters(metadata_equals={"court": "Supreme Court"})
    kept = apply_metadata_filters(chunks, filters)
    assert [c.text for c in kept] == ["A"]


def test_metadata_filters_none_returns_all(sample_corpus):
    assert len(apply_metadata_filters(sample_corpus, None)) == len(sample_corpus)


def test_public_chunk_authorized_for_any_user(access_public):
    chunk = make_chunk(text="public statute", visibility=VISIBILITY_PUBLIC)
    assert is_authorized(chunk, access_public)


def test_internal_requires_internal_or_admin(user_id):
    chunk = make_chunk(text="internal", visibility=VISIBILITY_INTERNAL)
    external = AccessContext(user_id=user_id, is_internal=False)
    internal = AccessContext(user_id=user_id, is_internal=True)
    admin = AccessContext(user_id=user_id, roles=frozenset({"admin"}))
    assert not is_authorized(chunk, external)
    assert is_authorized(chunk, internal)
    assert is_authorized(chunk, admin)


def test_matter_requires_membership(user_id, matter_id):
    chunk = make_chunk(
        text="matter work",
        visibility=VISIBILITY_MATTER,
        matter_id=matter_id,
    )
    outsider = AccessContext(user_id=user_id, matter_ids=frozenset())
    member = AccessContext(user_id=user_id, matter_ids=frozenset({matter_id}))
    assert not is_authorized(chunk, outsider)
    assert is_authorized(chunk, member)


def test_matter_without_matter_id_denied(user_id):
    chunk = make_chunk(text="broken", visibility=VISIBILITY_MATTER, matter_id=None)
    access = AccessContext(user_id=user_id, matter_ids=frozenset({uuid4()}))
    assert not is_authorized(chunk, access)


def test_private_only_uploader_or_admin(user_id, other_user_id):
    chunk = make_chunk(
        text="private",
        visibility=VISIBILITY_PRIVATE,
        uploaded_by=user_id,
    )
    owner = AccessContext(user_id=user_id)
    other = AccessContext(user_id=other_user_id)
    admin = AccessContext(user_id=other_user_id, roles=frozenset({"admin"}))
    assert is_authorized(chunk, owner)
    assert not is_authorized(chunk, other)
    assert is_authorized(chunk, admin)


def test_inactive_and_unready_chunks_denied(access_public):
    superseded = make_chunk(text="old", version_status="superseded")
    pending = make_chunk(text="pending", processing_status="pending")
    withdrawn = make_chunk(text="gone", version_status="withdrawn")
    assert not is_authorized(superseded, access_public)
    assert not is_authorized(pending, access_public)
    assert not is_authorized(withdrawn, access_public)


def test_unknown_visibility_denied(access_admin):
    chunk = make_chunk(text="weird", visibility="mystery")
    assert not is_authorized(chunk, access_admin)


def test_filter_indexed_corpus_combines_auth_and_metadata(
    sample_corpus, access_matter, matter_id
):
    filters = MetadataFilters(jurisdictions=frozenset({"India"}))
    kept = filter_indexed_corpus(
        sample_corpus,
        access=access_matter,
        filters=filters,
    )
    # Must not include USA-CA, superseded, pending, or other user's private draft.
    texts = " ".join(c.text for c in kept)
    assert "California" not in texts
    assert "Superseded" not in texts
    assert "Unprocessed" not in texts
    assert "Someone else's private" not in texts
    assert any(c.matter_id == matter_id for c in kept)
    assert any(c.visibility == VISIBILITY_INTERNAL for c in kept)


def test_filter_search_hits_reranks(access_public):
    allowed = make_chunk(text="allowed contract", visibility=VISIBILITY_PUBLIC)
    blocked = make_chunk(text="blocked", version_status="superseded")
    hits = [
        hit_from_indexed(
            chunk_id=blocked.chunk_id,
            text=blocked.text,
            score=0.99,
            rank=1,
            channel="vector",
            source=blocked.source,
            visibility=blocked.visibility,
            matter_id=blocked.matter_id,
            version_status=blocked.version_status,
            processing_status=blocked.processing_status,
            uploaded_by=blocked.uploaded_by,
            jurisdiction=blocked.jurisdiction,
            trust_tier=blocked.trust_tier,
            source_type=blocked.source_type,
            metadata=blocked.metadata,
        ),
        hit_from_indexed(
            chunk_id=allowed.chunk_id,
            text=allowed.text,
            score=0.5,
            rank=2,
            channel="vector",
            source=allowed.source,
            visibility=allowed.visibility,
            matter_id=allowed.matter_id,
            version_status=allowed.version_status,
            processing_status=allowed.processing_status,
            uploaded_by=allowed.uploaded_by,
            jurisdiction=allowed.jurisdiction,
            trust_tier=allowed.trust_tier,
            source_type=allowed.source_type,
            metadata=allowed.metadata,
        ),
    ]
    filtered = filter_search_hits(hits, access=access_public)
    assert len(filtered) == 1
    assert filtered[0].chunk_id == allowed.chunk_id
    assert filtered[0].rank == 1


def test_apply_access_filters_smoke(sample_corpus, access_public):
    kept = apply_access_filters(sample_corpus, access_public)
    assert kept
    assert all(c.visibility == VISIBILITY_PUBLIC for c in kept)
    assert all(c.version_status == "active" for c in kept)
    assert all(c.processing_status in {"ready", "completed"} for c in kept)
