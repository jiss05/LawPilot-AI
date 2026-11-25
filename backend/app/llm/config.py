"""
Model configuration (SCRUM-19: "Model configuration is maintained separately").

All settings for the language model live in this one class, apart from the
authentication settings (app/core/config.py) and the ingestion settings
(app/ingestion/config.py). Changing the model, the server or a timeout is a
change to backend/.env only -- no agent or orchestrator code changes
(SCRUM-20: "Model configuration can be changed without rewriting agents").

Variables use the prefix LLM_. Two older names from .env.example are still
accepted so existing .env files keep working:

    OLLAMA_BASE_URL   -> LLM_OLLAMA_BASE_URL
    OLLAMA_MODEL      -> LLM_MODEL

Example backend/.env:

    LLM_PROVIDER=ollama
    LLM_OLLAMA_BASE_URL=http://localhost:11434
    LLM_MODEL=qwen2.5:7b-instruct
    LLM_FALLBACK_MODEL=qwen2.5:3b-instruct
    LLM_TEMPERATURE=0.2
    LLM_REQUEST_TIMEOUT_SECONDS=120
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "qwen2.5:7b-instruct"


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Which backend serves the model. "ollama" for real use; "fake" returns
    # canned answers so the API and tests run without Ollama installed.
    provider: str = "ollama"

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("LLM_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"),
    )

    # Ollama model tag. Any Qwen tag pulled with `ollama pull <tag>` works.
    model: str = Field(
        default=DEFAULT_MODEL,
        validation_alias=AliasChoices("LLM_MODEL", "OLLAMA_MODEL"),
    )
    # Optional smaller model used when the main model fails or times out.
    fallback_model: str | None = None

    # Generation defaults (agents may override per request).
    temperature: float = 0.2
    top_p: float = 0.9
    max_output_tokens: int = 1024
    context_window: int = 8192
    # How long Ollama keeps the model loaded between requests.
    keep_alive: str = "10m"

    # Failure handling (SCRUM-20: "Timeouts and failures are handled safely").
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 120.0
    max_retries: int = 1
    retry_backoff_seconds: float = 1.0

    # Write one row per model call to the model_runs table
    # (SCRUM-20: "Model execution details are recorded").
    record_runs: bool = True

    @field_validator("provider")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str) -> str:
        # .env.example ships with an empty OLLAMA_MODEL=; treat it as "not set".
        return value.strip() or DEFAULT_MODEL

    @field_validator("fallback_model")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


@lru_cache
def get_model_settings() -> ModelSettings:
    return ModelSettings()
