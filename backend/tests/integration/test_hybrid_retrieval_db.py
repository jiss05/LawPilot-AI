"""
SCRUM-16 acceptance criteria, tested against real PostgreSQL + Qdrant:
  * Semantic and keyword searches return relevant results.
  * Retrieval rankings are combined correctly.
  * Duplicate chunks are removed.
  * Metadata and authorization filters are applied.
  * Relevant source information is returned with retrieved chunks.
"""

import pytest

from app.rag.ranking import DEFAULT_RRF_K
from app.rag.store_retriever import LegalSearchService, access_context_for, keyword_candidates
from app.rag.types import MetadataFilters

from .helpers import ingest_statute, make_user


@pytest.fixture
def admin(db):
    return make_user(db, "ADMIN")


@pytest.fixture
def client_user(db):
    return make_user(db, "CLIENT")


@pytest.fixture
def lawyer(db):
    return make_user(db, "LAWYER")


def search(db, settings, user, query, **kwargs):
    return LegalSearchService(settings).search(db, query, access=access_context_for(user), **kwargs)


def test_keyword_channel_finds_exact_legal_terms(db, settings, admin, client_user):
    ingest_statute(db, settings, admin)
    hits = keyword_candidates(db, "penalty stipulated", access_context_for(client_user), None, 5)
    assert hits, "keyword search returned nothing"
    response = search(db, settings, client_user, "penalty stipulated")
    assert response.results[0].source.section_ref == "Section 74"


def test_both_channels_contribute_and_rrf_scores_add_up(db, settings, admin, client_user):
    ingest_statute(db, settings, admin)
    response = search(db, settings, client_user, "compensation for breach of contract", top_k=5)
    assert response.vector_candidates > 0 and response.keyword_candidates > 0
    both = [r for r in response.results if set(r.channels) == {"keyword", "vector"}]
    assert both, "expected at least one chunk found by both searches"
    # RRF: a chunk's score is the sum of 1/(k + rank) over the channels that found it,
    # so it can never exceed 2/(k+1) and is at least 1/(k + candidates).
    for result in response.results:
        assert 0 < result.score <= 2 / (DEFAULT_RRF_K + 1) + 1e-9
    scores = [r.score for r in response.results]
    assert scores == sorted(scores, reverse=True)


def test_duplicate_chunks_removed(db, settings, admin, client_user):
    # The same Act uploaded twice as two different sources -> identical chunk texts.
    ingest_statute(db, settings, admin, title="Copy A")
    ingest_statute(db, settings, admin, title="Copy B")
    response = search(db, settings, client_user, "penalty stipulated breach", top_k=10)
    texts = [r.text for r in response.results]
    assert len(texts) == len(set(texts))
    assert len({r.chunk_id for r in response.results}) == len(response.results)


def test_source_information_returned(db, settings, admin, client_user):
    source, version, document = ingest_statute(db, settings, admin)
    top = search(db, settings, client_user, "penalty stipulated").results[0]
    assert top.source.source_id == source.id
    assert top.source.source_title == "Sample Contract Act, 1872"
    assert top.source.document_id == document.id
    assert top.source.url == "https://www.indiacode.nic.in/example"
    assert top.source.citation == "Section 74, p. 3"
    assert top.metadata["version_label"] == "As amended 2023"
    assert top.metadata["page_start"] == 3


def test_metadata_filters(db, settings, admin, client_user):
    ingest_statute(db, settings, admin)
    only_judgments = MetadataFilters(source_types=frozenset({"judgment"}))
    assert search(db, settings, client_user, "compensation", filters=only_judgments).results == []
    other_country = MetadataFilters(jurisdictions=frozenset({"Singapore"}))
    assert search(db, settings, client_user, "compensation", filters=other_country).results == []
    india = MetadataFilters(jurisdictions=frozenset({"India"}))
    assert search(db, settings, client_user, "compensation", filters=india).results


def test_internal_documents_hidden_from_clients(db, settings, admin, client_user, lawyer):
    ingest_statute(db, settings, admin, visibility="internal")
    assert search(db, settings, client_user, "compensation").results == []
    assert search(db, settings, lawyer, "compensation").results
    assert search(db, settings, admin, "compensation").results


def test_private_documents_only_for_uploader_and_admin(db, settings, admin, client_user, lawyer):
    ingest_statute(db, settings, lawyer, visibility="private")  # lawyer uploaded it
    assert search(db, settings, lawyer, "compensation").results
    assert search(db, settings, client_user, "compensation").results == []
    assert search(db, settings, admin, "compensation").results


def test_unactivated_versions_are_never_returned(db, settings, admin, client_user):
    ingest_statute(db, settings, admin, activate=False)  # indexed, but still "pending"
    response = search(db, settings, client_user, "compensation")
    assert response.vector_candidates > 0      # Qdrant has the vectors ...
    assert response.results == []              # ... but inactive editions are filtered out


def test_vector_store_down_degrades_to_keyword_search(db, settings, admin, client_user):
    ingest_statute(db, settings, admin)
    down = settings.model_copy(update={"qdrant_url": "http://127.0.0.1:1", "qdrant_timeout_seconds": 1})
    response = search(db, down, client_user, "penalty stipulated")
    assert response.degraded == ["vector"]
    assert response.results and response.results[0].channels == ("keyword",)
