
from app.agents.base import AgentContext
from app.agents.default_agents import LawyerAgent, NO_LEGAL_EVIDENCE_MESSAGE
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.orchestration.state import (
    INTENT_DOCUMENT_DRAFTING,
    INTENT_LEGAL_INFORMATION,
)


def create_gateway(reply="Test legal research answer [1]."):
    provider = FakeProvider([reply])

    gateway = ModelGateway(
        ModelSettings(provider="fake"),
        provider=provider,
        recorder=InMemoryRunRecorder(),
    )

    return gateway, provider


def sample_sources():
    return [
        {
            "chunk_id": "source-001",
            "text": "Sample legal provision for testing legal research.",
            "source_title": "Test Legal Authority",
            "citation": "Test citation",
            "url": None,
        }
    ]


def test_lawyer_agent_produces_research_answer_with_citations():
    gateway, provider = create_gateway(
        "The supplied authority supports this legal proposition [1]."
    )

    agent = LawyerAgent()

    context = AgentContext(
        message="Research the relevant legal principles.",
        intent=INTENT_LEGAL_INFORMATION,
        user_roles=frozenset({"LAWYER"}),
        sources=sample_sources(),
    )

    result = agent.run(context, gateway)

    assert result.content.startswith("The supplied authority")
    assert len(result.citations) == 1
    assert result.citations[0]["ref"] == 1
    assert result.citations[0]["source_title"] == "Test Legal Authority"
    assert len(provider.calls) == 1


def test_lawyer_agent_receives_research_instructions_and_sources():
    gateway, provider = create_gateway()
    agent = LawyerAgent()

    context = AgentContext(
        message="Analyse the legal position and counterarguments.",
        intent=INTENT_LEGAL_INFORMATION,
        user_roles=frozenset({"LAWYER"}),
        sources=sample_sources(),
    )

    agent.run(context, gateway)

    request = provider.calls[0][0]
    system_prompt = request.messages[0].content
    user_prompt = request.messages[-1].content

    assert "LEGAL RESEARCH" in system_prompt
    assert "ARGUMENT ANALYSIS" in system_prompt
    assert "counterarguments" in system_prompt.lower()
    assert "LEGAL DRAFTING" in system_prompt
    assert "Test Legal Authority" in user_prompt
    assert "Sample legal provision" in user_prompt


def test_lawyer_agent_includes_drafting_instructions():
    gateway, provider = create_gateway(
        "Draft prepared with placeholders for missing facts."
    )

    agent = LawyerAgent()

    context = AgentContext(
        message="Prepare a legal draft using the available facts.",
        intent=INTENT_DOCUMENT_DRAFTING,
        user_roles=frozenset({"LAWYER"}),
        sources=sample_sources(),
    )

    result = agent.run(context, gateway)

    assert "Draft prepared" in result.content

    system_prompt = provider.calls[0][0].messages[0].content

    assert "[PARTY NAME]" in system_prompt
    assert "review by a qualified" in system_prompt.lower()


def test_lawyer_agent_returns_safe_message_without_sources():
    gateway, provider = create_gateway()
    agent = LawyerAgent()

    context = AgentContext(
        message="Research a legal question.",
        intent=INTENT_LEGAL_INFORMATION,
        user_roles=frozenset({"LAWYER"}),
        sources=[],
    )

    result = agent.run(context, gateway)

    assert result.content == NO_LEGAL_EVIDENCE_MESSAGE
    assert result.citations == []
    assert result.metadata["safe_fallback"] is True
    assert result.metadata["evidence"] == "none"
    assert provider.calls == []
