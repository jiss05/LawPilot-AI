"""
Qdrant vector store (SCRUM-15).

Acceptance criteria:
  * "Vectors are stored in Qdrant."
  * "Chunk identifiers remain consistent across databases."
  * "Metadata is associated with the correct vectors."

ONE ID, TWO DATABASES
---------------------
Every Qdrant point uses the SAME UUID as its row in PostgreSQL
`document_chunks.id` (BRD §8.4: "Store stable PostgreSQL chunk IDs as Qdrant
point IDs"). So a vector hit can always be joined back to its chunk, page,
document, edition and source, and re-indexing overwrites the same points
instead of creating duplicates.

WHAT A POINT LOOKS LIKE (collection "legal_chunks_v1")
------------------------------------------------------
    id       = document_chunks.id
    vector   = [384 numbers]
    payload  = {
        chunk_id, knowledge_document_id, source_version_id, source_id,
        chunk_index, section_ref, page_number, page_end,
        source_title, source_type, jurisdiction, trust_tier, publisher,
        visibility, matter_id, uploaded_by,
        content_hash, embedding_model, text_preview
    }
The payload carries everything needed to FILTER inside Qdrant (visibility,
jurisdiction, source type ...) and to show a result. The full text stays in
PostgreSQL, the system of record (BRD §8.4: "keep vector payload size
reasonable").

CONNECTING
----------
    QDRANT_URL=http://localhost:6333   -> the Qdrant Docker container
    QDRANT_URL=:memory:                -> embedded, in-process (tests)
    QDRANT_URL=path:./storage/qdrant   -> embedded, saved to a folder
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from app.ingestion.config import IngestionSettings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode

logger = logging.getLogger(__name__)

# Payload fields we filter on; Qdrant builds an index for each.
FILTER_FIELDS = (
    "knowledge_document_id",
    "source_version_id",
    "source_id",
    "visibility",
    "jurisdiction",
    "source_type",
    "trust_tier",
    "matter_id",
    "uploaded_by",
)

_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def get_qdrant_client(settings: IngestionSettings):
    """
    One client per address for the whole process. For the embedded modes
    this is required: two ":memory:" clients would be two separate empty
    databases, and a "path:" folder can only be opened once.
    """
    from qdrant_client import QdrantClient

    url = settings.qdrant_url
    with _clients_lock:
        if url not in _clients:
            if url == ":memory:":
                _clients[url] = QdrantClient(location=":memory:")
            elif url.startswith("path:"):
                _clients[url] = QdrantClient(path=url[len("path:"):])
            else:
                _clients[url] = QdrantClient(
                    url=url,
                    api_key=settings.qdrant_api_key,
                    timeout=settings.qdrant_timeout_seconds,
                    # The docker-compose image tracks "latest"; skip the strict
                    # client/server version handshake (we only use stable APIs).
                    check_compatibility=False,
                )
        return _clients[url]


def _unavailable(exc: Exception, settings: IngestionSettings) -> ExtractionError:
    return ExtractionError(
        ExtractionErrorCode.VECTOR_STORE_UNAVAILABLE,
        f"Qdrant is not reachable at {settings.qdrant_url}. Is the qdrant container running?",
        details={"reason": str(exc)[:300]},
    )


@dataclass
class VectorPoint:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class VectorHit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any]


class QdrantVectorStore:
    def __init__(self, settings: IngestionSettings, client=None) -> None:
        self.settings = settings
        self.collection = settings.qdrant_collection
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = get_qdrant_client(self.settings)
        return self._client

    # ------------------------------------------------------------------ #
    # Collection setup
    # ------------------------------------------------------------------ #
    def ensure_collection(self, dimension: int) -> None:
        """
        Create the collection on first use. If it already exists with a
        different vector size, the embedding model was changed without a
        new collection name: refuse, instead of mixing incompatible vectors.
        """
        from qdrant_client import models

        try:
            if not self.client.collection_exists(self.collection):
                logger.info("Creating Qdrant collection %s (dim=%s)", self.collection, dimension)
                self.client.create_collection(
                    collection_name=self.collection,
                    # COSINE distance: compares the direction of vectors,
                    # the usual choice for text embeddings.
                    vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
                )
                for field in FILTER_FIELDS:
                    self.client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                return
            info = self.client.get_collection(self.collection)
        except ExtractionError:
            raise
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc

        existing = info.config.params.vectors.size
        if existing != dimension:
            raise ExtractionError(
                ExtractionErrorCode.VECTOR_DIMENSION_MISMATCH,
                f"Collection '{self.collection}' stores {existing}-dimensional vectors but the "
                f"embedding model produces {dimension}. Use a new INGESTION_QDRANT_COLLECTION "
                "name (e.g. legal_chunks_v2) and re-index.",
                details={"collection": self.collection, "existing": existing, "model": dimension},
            )

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    def _document_filter(self, document_id: uuid.UUID):
        from qdrant_client import models

        return models.Filter(
            must=[models.FieldCondition(key="knowledge_document_id", match=models.MatchValue(value=str(document_id)))]
        )

    def replace_document_points(self, document_id: uuid.UUID, points: list[VectorPoint]) -> None:
        """Remove this document's old vectors, then write the new ones."""
        from qdrant_client import models

        try:
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(filter=self._document_filter(document_id)),
                wait=True,
            )
            for start in range(0, len(points), 256):
                batch = points[start : start + 256]
                self.client.upsert(
                    collection_name=self.collection,
                    points=[models.PointStruct(id=str(p.id), vector=p.vector, payload=p.payload) for p in batch],
                    wait=True,  # return only once Qdrant has stored them
                )
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc

    def delete_document(self, document_id: uuid.UUID) -> None:
        from qdrant_client import models

        try:
            if self.client.collection_exists(self.collection):
                self.client.delete(
                    collection_name=self.collection,
                    points_selector=models.FilterSelector(filter=self._document_filter(document_id)),
                    wait=True,
                )
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def count_document(self, document_id: uuid.UUID) -> int:
        try:
            return self.client.count(
                collection_name=self.collection,
                count_filter=self._document_filter(document_id),
                exact=True,
            ).count
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc

    def retrieve(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, VectorHit]:
        """Fetch points by id (used to verify that ids and payloads match)."""
        try:
            records = self.client.retrieve(
                collection_name=self.collection,
                ids=[str(i) for i in ids],
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc
        return {uuid.UUID(str(r.id)): VectorHit(uuid.UUID(str(r.id)), 0.0, r.payload or {}) for r in records}

    def search(self, vector: list[float], *, limit: int, query_filter=None) -> list[VectorHit]:
        try:
            if not self.client.collection_exists(self.collection):
                return []
            response = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise _unavailable(exc, self.settings) from exc
        return [VectorHit(uuid.UUID(str(p.id)), float(p.score), p.payload or {}) for p in response.points]

    def health(self) -> dict[str, Any]:
        """Used by GET /api/v1/health/ready."""
        try:
            exists = self.client.collection_exists(self.collection)
            points = self.client.count(self.collection, exact=False).count if exists else 0
            return {"status": "ok", "collection": self.collection, "collection_exists": exists, "points": points}
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)[:200]}
