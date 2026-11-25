"""The interface every model provider implements (Ollama, fake, future ones)."""

from __future__ import annotations

from typing import Any, Protocol

from app.llm.types import GenerationRequest, ProviderResponse


class ModelProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest, model: str) -> ProviderResponse:
        """Return one reply, or raise a ModelError subclass."""

    def list_models(self) -> list[str]: ...

    def health(self, model: str) -> dict[str, Any]: ...
