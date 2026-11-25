"""
Language model access (Sprint 3: SCRUM-19 Ollama + Qwen, SCRUM-20 Model Gateway).

Agents use only:
    from app.llm import ChatMessage, GenerationRequest, ModelError, get_model_gateway
See app/llm/README.md.
"""

from app.llm.gateway import ModelGateway, get_model_gateway, set_model_gateway
from app.llm.types import (
    ChatMessage,
    GenerationRequest,
    GenerationResult,
    ModelError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)

__all__ = [
    "ChatMessage",
    "GenerationRequest",
    "GenerationResult",
    "ModelError",
    "ModelGateway",
    "ModelResponseError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "get_model_gateway",
    "set_model_gateway",
]
