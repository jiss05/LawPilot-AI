"""SCRUM-20: ModelGateway retries, falls back, records runs and hides provider details."""

import pytest

from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway, parse_json_object
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import DatabaseRunRecorder, InMemoryRunRecorder
from app.llm.types import (
    ChatMessage,
    GenerationRequest,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)

REQ = GenerationRequest(messages=[ChatMessage("user", "hello")], prompt_version="test.v1", purpose="test")


def make(replies, **settings):
    settings = {"model": "qwen2.5:7b-instruct", **settings}
    s = ModelSettings(provider="fake", retry_backoff_seconds=0, **settings)
    provider, recorder = FakeProvider(replies), InMemoryRunRecorder()
    return ModelGateway(s, provider=provider, recorder=recorder, sleep=lambda _: None), provider, recorder


def test_success_returns_result_and_records_run():
    gw, _, rec = make(["Answer"])
    result = gw.generate(REQ)
    assert result.text == "Answer"
    assert result.provider == "fake" and result.model == "qwen2.5:7b-instruct"
    assert result.run_id == rec.runs[0].id
    run = rec.runs[0]
    assert run.status == "succeeded" and run.prompt_version == "test.v1"
    assert run.model_name == "qwen2.5" and run.model_tag == "qwen2.5:7b-instruct"
    assert run.parameters["purpose"] == "test"
    assert run.token_metrics["completion_tokens"] == 1


def test_transient_error_is_retried():
    gw, provider, rec = make([ModelTimeoutError("slow"), "Recovered"], max_retries=1)
    result = gw.generate(REQ)
    assert result.text == "Recovered" and result.attempts == 2
    assert [r.status for r in rec.runs] == ["failed", "succeeded"]
    assert rec.runs[0].error_code == "model_timeout"


def test_falls_back_to_second_model():
    gw, provider, _ = make([ModelUnavailableError("down"), "From fallback"],
                           max_retries=0, fallback_model="qwen2.5:3b-instruct")
    result = gw.generate(REQ)
    assert result.used_fallback and result.text == "From fallback"
    assert [m for _, m in provider.calls] == ["qwen2.5:7b-instruct", "qwen2.5:3b-instruct"]


def test_non_retryable_error_skips_retries():
    gw, provider, _ = make([ModelResponseError("bad")], max_retries=3)
    with pytest.raises(ModelResponseError):
        gw.generate(REQ)
    assert len(provider.calls) == 1


def test_gives_up_after_retries_with_model_error():
    gw, provider, rec = make([ModelUnavailableError("down")] * 5, max_retries=2)
    with pytest.raises(ModelUnavailableError):
        gw.generate(REQ)
    assert len(provider.calls) == 3 and all(r.status == "failed" for r in rec.runs)


def test_unexpected_provider_crash_is_wrapped():
    gw, _, rec = make([RuntimeError("secret stack detail")], max_retries=0)
    with pytest.raises(ModelResponseError) as info:
        gw.generate(REQ)
    assert "secret" not in str(info.value)
    assert rec.runs[0].error_code == "provider_error"


def test_changing_model_needs_no_agent_change():
    gw, provider, _ = make(["ok"], model="qwen2.5:14b")
    gw.generate(REQ)
    assert provider.calls[0][1] == "qwen2.5:14b"


def test_generate_json():
    gw, provider, _ = make(['```json\n{"intent": "legal_research"}\n```'])
    assert gw.generate_json(GenerationRequest(messages=REQ.messages)) == {"intent": "legal_research"}
    assert provider.calls[0][0].json_mode is True


@pytest.mark.parametrize("text", ["no json here", "[1, 2]", "{broken"])
def test_parse_json_object_rejects_bad_output(text):
    with pytest.raises(ModelResponseError):
        parse_json_object(text)


def test_parse_json_object_finds_object_in_text():
    assert parse_json_object('Sure! {"intent": "out_of_scope"} hope that helps') == {"intent": "out_of_scope"}


def test_empty_messages_rejected():
    gw, _, _ = make([])
    with pytest.raises(ValueError):
        gw.generate(GenerationRequest(messages=[]))


def test_database_recorder_failure_does_not_break_request():
    def broken_session():
        raise RuntimeError("database down")

    s = ModelSettings(provider="fake")
    gw = ModelGateway(s, provider=FakeProvider(["fine"]), recorder=DatabaseRunRecorder(broken_session))
    result = gw.generate(REQ)
    assert result.text == "fine" and result.run_id is None
