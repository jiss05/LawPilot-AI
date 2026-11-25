"""
Provider-independent request/response types for the model gateway.

Agents only ever see these types. Nothing here mentions Ollama, so a
different provider can be plugged in without touching agent code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass
class GenerationRequest:
    messages: list[ChatMessage]
    # Name of the prompt template that produced the messages, stored with the
    # run so answers can be traced back to the prompt (e.g. "client_agent.v1").
    prompt_version: str = "adhoc.v1"
    # Optional overrides; None means "use ModelSettings".
    temperature: float | None = None
    max_output_tokens: int | None = None
    # Ask the model for a JSON object (used by the request classifier).
    json_mode: bool = False
    # Fixed random seed for repeatable output (used by the evaluation).
    seed: int | None = None
    # Free-form label for logs, e.g. "classifier" or "lawyer_agent".
    purpose: str = "generation"


@dataclass
class ProviderResponse:
    """What a provider returns for one successful call."""

    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    raw_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    """What the gateway returns to agents."""

    text: str
    provider: str
    model: str
    duration_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    used_fallback: bool = False
    attempts: int = 1
    run_id: UUID | None = None


# --------------------------------------------------------------------------- #
# Errors. Agents catch ModelError; the subclasses say what went wrong
# without exposing provider internals (URLs, stack traces) to users.
# --------------------------------------------------------------------------- #
class ModelError(Exception):
    code = "model_error"
    retryable = False


class ModelUnavailableError(ModelError):
    """Server down, connection refused, or model not pulled."""

    code = "model_unavailable"
    retryable = True


class ModelTimeoutError(ModelError):
    code = "model_timeout"
    retryable = True


class ModelResponseError(ModelError):
    """The server answered but the answer was unusable (bad status, empty, bad JSON)."""

    code = "model_bad_response"
    retryable = False
