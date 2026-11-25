"""
Fake provider: canned replies without a model server.

Used by the unit tests, and by developers who want to run the API with
LLM_PROVIDER=fake when Ollama is not installed.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable

from app.llm.types import GenerationRequest, ModelError, ProviderResponse

Responder = Callable[[GenerationRequest, str], str]


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        replies: list[str | Exception] | None = None,
        responder: Responder | None = None,
    ) -> None:
        # Replies are used in order; an Exception in the list is raised instead.
        self._queue: deque[str | Exception] = deque(replies or [])
        self._responder = responder
        self.calls: list[tuple[GenerationRequest, str]] = []

    def generate(self, request: GenerationRequest, model: str) -> ProviderResponse:
        self.calls.append((request, model))
        if self._queue:
            reply = self._queue.popleft()
        elif self._responder:
            reply = self._responder(request, model)
        else:
            reply = _default_reply(request)
        if isinstance(reply, Exception):
            raise reply
        return ProviderResponse(
            text=reply,
            model=model,
            prompt_tokens=sum(len(m.content.split()) for m in request.messages),
            completion_tokens=len(reply.split()),
            finish_reason="stop",
        )

    def list_models(self) -> list[str]:
        return ["fake:latest"]

    def health(self, model: str) -> dict[str, Any]:
        return {"status": "ok", "provider": self.name, "model": model, "model_pulled": True}


def _default_reply(request: GenerationRequest) -> str:
    if request.json_mode:
        return "{}"
    question = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    return f"[fake model] I received your question: {question[:200]}"


__all__ = ["FakeProvider", "ModelError"]
