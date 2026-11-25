"""
Ollama provider (SCRUM-19: "Ollama is accessible from the backend").

Talks to Ollama's HTTP API:
    POST /api/chat     generate a reply (stream disabled)
    GET  /api/tags     models pulled on the server
    GET  /api/version  server version (health check)

Inside Docker the backend reaches Ollama on the host through
http://host.docker.internal:11434 (set in docker-compose.yml).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.config import ModelSettings
from app.llm.types import (
    GenerationRequest,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    ProviderResponse,
)


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: ModelSettings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
        )

    # ------------------------------------------------------------------ #
    def generate(self, request: GenerationRequest, model: str) -> ProviderResponse:
        s = self.settings
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "keep_alive": s.keep_alive,
            "options": {
                "temperature": s.temperature if request.temperature is None else request.temperature,
                "top_p": s.top_p,
                "num_ctx": s.context_window,
                "num_predict": request.max_output_tokens or s.max_output_tokens,
            },
        }
        if request.seed is not None:
            payload["options"]["seed"] = request.seed
        if request.json_mode:
            payload["format"] = "json"

        data = self._post("/api/chat", payload, model)
        text = ((data.get("message") or {}).get("content") or "").strip()
        if not text:
            raise ModelResponseError(f"Model '{model}' returned an empty response.")

        metrics = {
            key: data[key]
            for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
            if key in data
        }
        return ProviderResponse(
            text=text,
            model=data.get("model") or model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            finish_reason=data.get("done_reason"),
            raw_metrics=metrics,
        )

    def list_models(self) -> list[str]:
        data = self._get("/api/tags")
        return [m.get("name") for m in data.get("models", []) if m.get("name")]

    def health(self, model: str) -> dict[str, Any]:
        """Is the server up, and is the configured model pulled?"""
        try:
            version = self._get("/api/version").get("version")
            models = self.list_models()
        except (ModelUnavailableError, ModelTimeoutError, ModelResponseError) as exc:
            return {"status": "unavailable", "provider": self.name, "error": exc.code}
        pulled = _model_present(model, models)
        return {
            "status": "ok" if pulled else "model_missing",
            "provider": self.name,
            "server_version": version,
            "model": model,
            "model_pulled": pulled,
            **({} if pulled else {"hint": f"Run: ollama pull {model}"}),
        }

    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: dict, model: str) -> dict:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Ollama did not answer in time (model {model}).") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError("Cannot reach the Ollama server.") from exc
        if response.status_code == 404:
            # Ollama answers 404 when the model has not been pulled.
            raise ModelUnavailableError(f"Model '{model}' is not available on the Ollama server.")
        if response.status_code >= 500:
            raise ModelUnavailableError(f"Ollama server error ({response.status_code}).")
        if response.status_code >= 400:
            raise ModelResponseError(f"Ollama rejected the request ({response.status_code}).")
        try:
            return response.json()
        except ValueError as exc:
            raise ModelResponseError("Ollama returned invalid JSON.") from exc

    def _get(self, path: str) -> dict:
        try:
            response = self._client.get(path, timeout=self.settings.connect_timeout_seconds * 2)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("Ollama did not answer in time.") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelResponseError(f"Ollama error ({exc.response.status_code}).") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelUnavailableError("Cannot reach the Ollama server.") from exc


def _model_present(model: str, pulled: list[str]) -> bool:
    """'qwen2.5' matches 'qwen2.5:latest'; full tags must match exactly."""
    wanted = model if ":" in model else f"{model}:latest"
    return wanted in pulled or model in pulled
