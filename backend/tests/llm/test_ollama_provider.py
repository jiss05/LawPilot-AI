"""SCRUM-19: the Ollama provider talks to the HTTP API and maps failures safely."""

import httpx
import pytest

from app.llm.config import ModelSettings
from app.llm.providers.ollama import OllamaProvider
from app.llm.types import (
    ChatMessage,
    GenerationRequest,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)


def provider_with(handler):
    settings = ModelSettings(provider="ollama", ollama_base_url="http://ollama.test", model="qwen2.5:7b-instruct")
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaProvider(settings, client=client)


REQUEST = GenerationRequest(messages=[ChatMessage("user", "What is Section 138?")], max_output_tokens=50)


def test_generate_sends_model_options_and_parses_reply():
    seen = {}

    def handler(request):
        seen.update(request=request, body=__import__("json").loads(request.content))
        return httpx.Response(200, json={
            "model": "qwen2.5:7b-instruct", "message": {"role": "assistant", "content": " Cheque dishonour. "},
            "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 3, "total_duration": 1000,
        })

    reply = provider_with(handler).generate(REQUEST, "qwen2.5:7b-instruct")
    assert seen["request"].url.path == "/api/chat"
    assert seen["body"]["model"] == "qwen2.5:7b-instruct"
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["num_predict"] == 50
    assert "format" not in seen["body"]
    assert "seed" not in seen["body"]["options"]
    assert reply.text == "Cheque dishonour."
    assert (reply.prompt_tokens, reply.completion_tokens) == (12, 3)
    assert reply.raw_metrics == {"total_duration": 1000}


def test_seed_is_sent_when_set():
    def handler(request):
        assert __import__("json").loads(request.content)["options"]["seed"] == 42
        return httpx.Response(200, json={"message": {"content": "ok"}})

    provider_with(handler).generate(GenerationRequest(messages=REQUEST.messages, seed=42), "m")


def test_json_mode_sets_format():
    def handler(request):
        assert __import__("json").loads(request.content)["format"] == "json"
        return httpx.Response(200, json={"message": {"content": "{}"}})

    provider_with(handler).generate(
        GenerationRequest(messages=REQUEST.messages, json_mode=True), "qwen2.5:7b-instruct")


@pytest.mark.parametrize("handler, error", [
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), ModelUnavailableError),
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), ModelTimeoutError),
    (lambda r: httpx.Response(404, json={"error": "model not found"}), ModelUnavailableError),
    (lambda r: httpx.Response(500), ModelUnavailableError),
    (lambda r: httpx.Response(400), ModelResponseError),
    (lambda r: httpx.Response(200, json={"message": {"content": "  "}}), ModelResponseError),
    (lambda r: httpx.Response(200, text="not json"), ModelResponseError),
])
def test_failures_become_model_errors(handler, error):
    with pytest.raises(error):
        provider_with(handler).generate(REQUEST, "qwen2.5:7b-instruct")


def test_health_reports_missing_model_with_hint():
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.0"})
        return httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})

    info = provider_with(handler).health("qwen2.5:7b-instruct")
    assert info["status"] == "model_missing"
    assert info["hint"] == "Run: ollama pull qwen2.5:7b-instruct"


def test_health_ok_and_latest_tag_matching():
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.0"})
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:latest"}]})

    assert provider_with(handler).health("qwen2.5")["status"] == "ok"


def test_health_when_server_down():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert provider_with(handler).health("qwen2.5")["status"] == "unavailable"


def test_settings_accept_legacy_env_names(monkeypatch):
    # app.db.session calls load_dotenv(), which can put the new-style names
    # from a developer's .env into the environment; those would win.
    monkeypatch.delenv("LLM_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    s = ModelSettings(_env_file=None)
    assert s.ollama_base_url == "http://host.docker.internal:11434"
    assert s.model == "qwen2.5:14b"


def test_blank_model_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "")
    assert ModelSettings(_env_file=None).model == "qwen2.5:7b-instruct"
