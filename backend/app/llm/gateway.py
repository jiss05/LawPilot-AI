"""
ModelGateway (SCRUM-20): the single door between agents and the model.

    gateway = get_model_gateway()
    result = gateway.generate(GenerationRequest(
        messages=[ChatMessage("system", "..."), ChatMessage("user", question)],
        prompt_version="lawyer_agent.v1",
        purpose="lawyer_agent",
    ))
    result.text, result.model, result.run_id

Acceptance criteria and where they are met:

* Agents communicate through the ModelGateway interface
      -> agents import only this module and app.llm.types.
* Model configuration can be changed without rewriting agents
      -> provider, model, fallback, timeouts come from ModelSettings (.env).
* Timeouts and failures are handled safely
      -> connect/read timeouts, retry with backoff for transient errors,
         optional fallback model, and only ModelError subclasses ever
         leave the gateway (never raw httpx errors or stack traces).
* Model execution details are recorded
      -> one model_runs row per attempt (RunRecorder) + a structured log line.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from app.llm.config import ModelSettings, get_model_settings
from app.llm.providers.base import ModelProvider
from app.llm.run_recorder import (
    DatabaseRunRecorder,
    NullRunRecorder,
    RunRecord,
    RunRecorder,
)
from app.llm.types import (
    ChatMessage,
    GenerationRequest,
    GenerationResult,
    ModelError,
    ModelResponseError,
)

logger = logging.getLogger("app.llm.gateway")


class ModelGateway:
    def __init__(
        self,
        settings: ModelSettings | None = None,
        *,
        provider: ModelProvider | None = None,
        recorder: RunRecorder | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_model_settings()
        self.provider = provider or build_provider(self.settings)
        if recorder is None:
            recorder = DatabaseRunRecorder() if self.settings.record_runs else NullRunRecorder()
        self.recorder = recorder
        self._sleep = sleep

    # ------------------------------------------------------------------ #
    @property
    def model(self) -> str:
        return self.settings.model

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Return a reply or raise ModelError. Tries the main model, then the fallback."""
        if not request.messages:
            raise ValueError("GenerationRequest.messages must not be empty.")

        models = [self.settings.model]
        if self.settings.fallback_model and self.settings.fallback_model != self.settings.model:
            models.append(self.settings.fallback_model)

        attempts = 0
        last_error: ModelError | None = None
        for index, model in enumerate(models):
            for retry in range(self.settings.max_retries + 1):
                attempts += 1
                try:
                    result = self._call(request, model)
                except ModelError as exc:
                    last_error = exc
                    if not exc.retryable:
                        break  # same model would fail the same way; try fallback
                    if retry < self.settings.max_retries:
                        self._sleep(self.settings.retry_backoff_seconds * (2 ** retry))
                    continue
                result.used_fallback = index > 0
                result.attempts = attempts
                return result

        assert last_error is not None
        raise last_error

    def generate_json(self, request: GenerationRequest) -> dict[str, Any]:
        """Generate with JSON mode and parse the object. Raises ModelResponseError if it is not JSON."""
        request.json_mode = True
        result = self.generate(request)
        return parse_json_object(result.text)

    def health(self) -> dict[str, Any]:
        info = self.provider.health(self.settings.model)
        info["fallback_model"] = self.settings.fallback_model
        return info

    # ------------------------------------------------------------------ #
    def _call(self, request: GenerationRequest, model: str) -> GenerationResult:
        params = {
            "temperature": self.settings.temperature if request.temperature is None else request.temperature,
            "max_output_tokens": request.max_output_tokens or self.settings.max_output_tokens,
            "json_mode": request.json_mode,
            "seed": request.seed,
            "purpose": request.purpose,
        }
        started = time.perf_counter()
        try:
            response = self.provider.generate(request, model)
        except ModelError as exc:
            duration = _ms_since(started)
            self._record(request, model, params, duration, status="failed", error_code=exc.code)
            logger.warning(
                "model_call failed provider=%s model=%s purpose=%s duration_ms=%s error=%s",
                self.provider.name, model, request.purpose, duration, exc.code,
            )
            raise
        except Exception as exc:  # a provider bug must not leak details to the user
            duration = _ms_since(started)
            self._record(request, model, params, duration, status="failed", error_code="provider_error")
            logger.exception("model_call crashed provider=%s model=%s", self.provider.name, model)
            raise ModelResponseError("The model provider failed unexpectedly.") from exc

        duration = _ms_since(started)
        tokens = {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            **response.raw_metrics,
        }
        run_id = self._record(request, response.model, params, duration, status="succeeded",
                              tokens=tokens, finish_reason=response.finish_reason)
        logger.info(
            "model_call ok provider=%s model=%s purpose=%s duration_ms=%s prompt_tokens=%s completion_tokens=%s",
            self.provider.name, response.model, request.purpose, duration,
            response.prompt_tokens, response.completion_tokens,
        )
        return GenerationResult(
            text=response.text,
            provider=self.provider.name,
            model=response.model,
            duration_ms=duration,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            finish_reason=response.finish_reason,
            run_id=run_id,
        )

    def _record(self, request, model, params, duration, *, status, error_code=None,
                tokens=None, finish_reason=None):
        token_metrics = {k: v for k, v in (tokens or {}).items() if v is not None}
        if finish_reason:
            token_metrics["finish_reason"] = finish_reason
        return self.recorder.record(RunRecord(
            provider=self.provider.name,
            model_name=model.split(":")[0],
            model_tag=model,
            prompt_version=request.prompt_version,
            status=status,
            duration_ms=duration,
            parameters=params,
            token_metrics=token_metrics,
            error_code=error_code,
        ))


# --------------------------------------------------------------------------- #
def build_provider(settings: ModelSettings) -> ModelProvider:
    if settings.provider == "ollama":
        from app.llm.providers.ollama import OllamaProvider

        return OllamaProvider(settings)
    if settings.provider == "fake":
        from app.llm.providers.fake import FakeProvider

        return FakeProvider()
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.provider}'. Use 'ollama' or 'fake'.")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating ```json fences or text around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ModelResponseError("The model did not return JSON.")
        try:
            value = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise ModelResponseError("The model did not return valid JSON.") from exc
    if not isinstance(value, dict):
        raise ModelResponseError("The model returned JSON that is not an object.")
    return value


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


_gateway: ModelGateway | None = None
_lock = threading.Lock()


def get_model_gateway() -> ModelGateway:
    """One shared gateway (and HTTP connection pool) per process."""
    global _gateway
    if _gateway is None:
        with _lock:
            if _gateway is None:
                _gateway = ModelGateway()
    return _gateway


def set_model_gateway(gateway: ModelGateway | None) -> None:
    """Replace the shared gateway (tests, or after changing settings at runtime)."""
    global _gateway
    _gateway = gateway


__all__ = [
    "ChatMessage",
    "GenerationRequest",
    "GenerationResult",
    "ModelGateway",
    "build_provider",
    "get_model_gateway",
    "parse_json_object",
    "set_model_gateway",
]
