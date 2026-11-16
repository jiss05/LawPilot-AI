"""
Embeddings: turning text into vectors (SCRUM-15).

Acceptance criterion: "Embeddings are generated successfully."

WHAT IS AN EMBEDDING?
An embedding model reads a piece of text and outputs a fixed-length list
of numbers (a vector), e.g. 384 numbers. Texts with similar MEANING get
vectors that point in similar directions, even when they share no words:
"my flat was handed over late" lands near "compensation for breach of
contract". Qdrant stores these vectors and finds the nearest ones to a
question's vector. That is "semantic search".

WHY A PROVIDER INTERFACE?
The BRD (§18.1) says to choose the embedding model separately from the
chat model, and to re-index when it changes. Everything else in the
project talks to the small `EmbeddingProvider` interface below, so the
model can change with one setting (INGESTION_EMBEDDING_PROVIDER /
INGESTION_EMBEDDING_MODEL) and no other code.

    SentenceTransformerProvider  BRD default; runs locally on CPU
    OllamaEmbeddingProvider      if the team prefers models served by Ollama
    HashingEmbeddingProvider     no download at all; for tests and offline
                                 demos only (it matches words, not meaning)

Every provider returns vectors that are:
  * the same length for every text (`dimension`)
  * L2-normalised (length 1), so cosine similarity = dot product
  * checked: no NaN/infinite values, no empty vectors
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from typing import Protocol

from app.ingestion.config import IngestionSettings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """What every embedding engine must offer."""

    name: str        # e.g. "sentence-transformers:BAAI/bge-small-en-v1.5"
    dimension: int   # length of every vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------
def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def validate_vectors(vectors: list[list[float]], expected_count: int, dimension: int, name: str) -> None:
    """Raise EMBEDDING_FAILED unless every vector is complete and finite."""
    if len(vectors) != expected_count:
        raise ExtractionError(
            ExtractionErrorCode.EMBEDDING_FAILED,
            f"{name} returned {len(vectors)} vectors for {expected_count} texts.",
        )
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise ExtractionError(
                ExtractionErrorCode.EMBEDDING_FAILED,
                f"{name} returned a vector of size {len(vector)}; expected {dimension}.",
                details={"text_index": index},
            )
        if not all(math.isfinite(v) for v in vector):
            raise ExtractionError(
                ExtractionErrorCode.EMBEDDING_FAILED,
                f"{name} returned a vector containing NaN or infinite values.",
                details={"text_index": index},
            )
        if not any(vector):
            raise ExtractionError(
                ExtractionErrorCode.EMBEDDING_FAILED,
                f"{name} returned an all-zero vector (empty text?).",
                details={"text_index": index},
            )


# ---------------------------------------------------------------------------
# 1. sentence-transformers (BRD default)
# ---------------------------------------------------------------------------
class SentenceTransformerProvider:
    """
    Runs a sentence-transformers model in this Python process (CPU is fine
    for bge-small: roughly 50-200 chunks per second on a laptop).

    The model is loaded lazily on first use and kept for the life of the
    process, like the EasyOCR reader.
    """

    def __init__(self, model_name: str, query_instruction: str = "", batch_size: int = 32) -> None:
        self.model_name = model_name
        self.query_instruction = query_instruction
        self.batch_size = batch_size
        self.name = f"sentence-transformers:{model_name}"
        self._model = None
        self._dimension: int | None = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:
                        raise ExtractionError(
                            ExtractionErrorCode.EMBEDDING_FAILED,
                            "sentence-transformers is not installed. Run: pip install sentence-transformers",
                        ) from exc
                    logger.info("Loading embedding model %s ...", self.model_name)
                    try:
                        self._model = SentenceTransformer(self.model_name, device="cpu")
                    except Exception as exc:  # download / file errors
                        raise ExtractionError(
                            ExtractionErrorCode.EMBEDDING_FAILED,
                            f"Could not load embedding model '{self.model_name}'.",
                            details={"reason": str(exc)[:300]},
                        ) from exc
                    get_dim = getattr(self._model, "get_embedding_dimension", None) or \
                        self._model.get_sentence_embedding_dimension
                    self._dimension = int(get_dim())
        return self._model

    @property
    def dimension(self) -> int:
        self._load()
        return self._dimension  # type: ignore[return-value]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            vectors = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise ExtractionError(
                ExtractionErrorCode.EMBEDDING_FAILED,
                "The embedding model failed while encoding text.",
                details={"reason": str(exc)[:300]},
            ) from exc
        return [vector.tolist() for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self.query_instruction + text])[0]


# ---------------------------------------------------------------------------
# 2. Ollama
# ---------------------------------------------------------------------------
class OllamaEmbeddingProvider:
    """Calls Ollama's /api/embed endpoint (e.g. model "nomic-embed-text")."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0, batch_size: int = 32) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.batch_size = batch_size
        self.name = f"ollama:{model}"
        self._dimension: int | None = None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            try:
                response = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                vectors.extend(response.json()["embeddings"])
            except Exception as exc:
                raise ExtractionError(
                    ExtractionErrorCode.EMBEDDING_FAILED,
                    f"Ollama embedding request failed ({self.base_url}, model {self.model}).",
                    details={"reason": str(exc)[:300]},
                ) from exc
        return [_normalise([float(v) for v in vector]) for vector in vectors]

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = len(self._embed(["dimension probe"])[0])
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


# ---------------------------------------------------------------------------
# 3. Hashing (tests / offline only)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9]+")


class HashingEmbeddingProvider:
    """
    A "fake" embedding model that needs no download: every word (and pair of
    neighbouring words) is hashed into one of `dimension` slots. Texts that
    share words get similar vectors. It understands NO meaning or synonyms,
    so never use it for real legal search; it exists so tests and offline
    demos can exercise the whole pipeline with real vectors.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.name = f"hashing:{dimension}"

    def _vector(self, text: str) -> list[float]:
        words = _WORD_RE.findall(text.lower())
        features = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
        vector = [0.0] * self.dimension
        for feature in features:
            digest = hashlib.md5(feature.encode()).digest()
            slot = int.from_bytes(digest[:4], "little") % self.dimension
            vector[slot] += 1.0 if digest[4] % 2 == 0 else -1.0
        if not any(vector):  # e.g. text with no letters or digits
            vector[0] = 1.0
        return _normalise(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_providers: dict[tuple, EmbeddingProvider] = {}
_providers_lock = threading.Lock()


def get_embedding_provider(settings: IngestionSettings) -> EmbeddingProvider:
    """Return one shared provider per configuration (models load only once)."""
    kind = settings.embedding_provider.lower().strip()
    key = (kind, settings.embedding_model, settings.embedding_dimension, settings.ollama_base_url)
    with _providers_lock:
        if key not in _providers:
            if kind in {"sentence-transformers", "sentence_transformers", "st"}:
                _providers[key] = SentenceTransformerProvider(
                    settings.embedding_model,
                    settings.embedding_query_instruction,
                    settings.embedding_batch_size,
                )
            elif kind == "ollama":
                _providers[key] = OllamaEmbeddingProvider(
                    settings.ollama_base_url, settings.embedding_model,
                    batch_size=settings.embedding_batch_size,
                )
            elif kind == "hashing":
                _providers[key] = HashingEmbeddingProvider(settings.embedding_dimension)
            else:
                raise ValueError(
                    f"Unknown INGESTION_EMBEDDING_PROVIDER '{settings.embedding_provider}'. "
                    "Use sentence-transformers, ollama or hashing."
                )
        return _providers[key]
