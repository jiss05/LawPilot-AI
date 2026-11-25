"""
Baseline agents so the orchestrator works end to end today.

These are deliberately simple: a role-specific system prompt, the retrieved
sources as numbered context, and one call through the ModelGateway. The full
agents are separate stories and replace these by registering under the same
name in app/agents/registry.py:

    client         -> SCRUM-22 Develop Client Agent
    lawyer         -> SCRUM-23 Develop Lawyer Agent (+ SCRUM-24 drafting)
    judge_support  -> SCRUM-25 Develop Judge Support Agent
"""

from __future__ import annotations

from typing import Any

from app.agents.base import (
    CLIENT_AGENT,
    JUDGE_SUPPORT_AGENT,
    LAWYER_AGENT,
    AgentContext,
    AgentResult,
)
from app.llm.gateway import ModelGateway
from app.llm.types import ChatMessage, GenerationRequest
from app.orchestration.state import (
    INTENT_CASE_ANALYSIS,
    INTENT_DOCUMENT_DRAFTING,
    INTENT_LEGAL_INFORMATION,
)

MAX_HISTORY_MESSAGES = 6
MAX_SOURCE_CHARS = 1200

_GROUNDING = (
    "STRICT LEGAL EVIDENCE RULES:\n"
    "Use only the numbered SOURCES supplied in this request as evidence "
    "for legal claims, statutory provisions, case law and legal procedures.\n"
    "Cite every material legal claim using the supplied source numbers, "
    "for example [1] or [2].\n"
    "Never invent case names, citations, judgments, statutory sections, "
    "quotes or legal rules.\n"
    "If the supplied sources do not establish an answer, explicitly say "
    "that the available legal sources are insufficient.\n"
    "Distinguish established information from unanswered questions and "
    "identify what additional evidence is needed.\n"
    "Do not use general model knowledge to fill gaps in legal evidence."
)

NO_LEGAL_EVIDENCE_MESSAGE = (
    "I could not find supporting legal authorities in the available "
    "knowledge base for this question. I cannot provide a reliable, "
    "source-backed legal answer without relevant evidence. Please try "
    "rephrasing the question or ask the administrator to add the relevant "
    "legal materials to the knowledge base."
)
def format_sources(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "SOURCES: none found in the knowledge base."
    lines = ["SOURCES:"]
    for i, src in enumerate(sources, 1):
        label = src.get("source_title") or "Untitled source"
        if src.get("citation"):
            label += f", {src['citation']}"
        lines.append(f"[{i}] {label}\n{(src.get('text') or '')[:MAX_SOURCE_CHARS]}")
    return "\n\n".join(lines)


def citations_for(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ref": i,
            "chunk_id": s.get("chunk_id"),
            "source_title": s.get("source_title"),
            "citation": s.get("citation"),
            "url": s.get("url"),
        }
        for i, s in enumerate(sources, 1)
    ]


class PromptAgent:
    """An agent defined by a system prompt. Subclasses set the class attributes."""

    name = "base"
    description = ""
    system_prompt = ""
    prompt_version = "base.v1"

    def build_messages(self, ctx: AgentContext) -> list[ChatMessage]:
        system = f"{self.system_prompt}\n\n{_GROUNDING}"
        if ctx.handoff_from:
            system += (
                f"\n\nThis request was handed to you by the {ctx.handoff_from} agent "
                f"({ctx.handoff_reason or 'no reason given'}). Its draft answer is below; "
                "build on it rather than repeating it."
            )
        messages = [ChatMessage("system", system)]
        for turn in ctx.history[-MAX_HISTORY_MESSAGES:]:
            role = "assistant" if turn.get("role") == "assistant" else "user"
            messages.append(ChatMessage(role, turn.get("content", "")))
        if ctx.previous_outputs:
            last = ctx.previous_outputs[-1]
            messages.append(ChatMessage("assistant", last.get("content", "")))
        messages.append(ChatMessage("user", f"{format_sources(ctx.sources)}\n\nQUESTION:\n{ctx.message}"))
        return messages

    def handoff(self, ctx: AgentContext) -> tuple[str | None, str | None]:
        """Override to ask the orchestrator to pass the request on."""
        return None, None

    def run(self, ctx: AgentContext, gateway: ModelGateway) -> AgentResult:
        # Client and Lawyer Agents must have retrieved legal evidence.
        # Do not call the LLM when retrieval returned no sources.
        if self.name in (CLIENT_AGENT, LAWYER_AGENT) and not ctx.sources:
            handoff_to, reason = self.handoff(ctx)

            return AgentResult(
                content=NO_LEGAL_EVIDENCE_MESSAGE,
                citations=[],
                handoff_to=handoff_to,
                handoff_reason=reason,
                metadata={
                    "evidence": "none",
                    "safe_fallback": True,
                },
            )

        result = gateway.generate(GenerationRequest(
            messages=self.build_messages(ctx),
            prompt_version=self.prompt_version,
            purpose=f"{self.name}_agent",
        ))

        handoff_to, reason = self.handoff(ctx)

        return AgentResult(
            content=result.text,
            citations=citations_for(ctx.sources),
            handoff_to=handoff_to,
            handoff_reason=reason,
            model_run_id=result.run_id,
            metadata={
                "model": result.model,
                "duration_ms": result.duration_ms,
                "evidence": "retrieved",
            },
        )


class ClientAgent(PromptAgent):
    name = CLIENT_AGENT
    description = "Explains legal topics in plain language for members of the public."
    prompt_version = "client_agent.baseline.v1"
    system_prompt = (
        "You are LawPilot's assistant for members of the public in India. Explain the law "
        "in simple, everyday language, outline practical options and next steps, and suggest "
        "consulting a qualified advocate for decisions about a specific case. Do not give "
        "a definitive legal opinion."
    )

    def handoff(self, ctx):
        # Drafting court documents is the lawyer agent's job. The orchestrator
        # performs the handoff only if this user may use the lawyer agent.
        if ctx.intent == INTENT_DOCUMENT_DRAFTING and not ctx.handoff_from:
            return LAWYER_AGENT, "legal document drafting"
        return None, None


class LawyerAgent(PromptAgent):
    name = LAWYER_AGENT
    description = "Legal research and drafting support for advocates."
    prompt_version = "lawyer_agent.baseline.v1"
    system_prompt = (
        "You are LawPilot's research assistant for practising advocates in India. Be precise "
        "and technical: identify the governing statutes and sections, relevant principles and "
        "the strongest arguments on each side. For drafting requests, produce a structured "
        "draft with placeholders such as [PARTY NAME] for missing facts."
    )

    def handoff(self, ctx):
        # A lawyer asking for a plain-language explanation for a client.
        wants_plain = any(w in ctx.message.lower() for w in ("explain to my client", "plain language", "simple terms", "layman"))
        if ctx.intent == INTENT_LEGAL_INFORMATION and wants_plain and not ctx.handoff_from:
            return CLIENT_AGENT, "plain-language explanation for a client"
        return None, None


class JudgeSupportAgent(PromptAgent):
    name = JUDGE_SUPPORT_AGENT
    description = "Neutral case analysis support for judges and court staff."
    prompt_version = "judge_support_agent.baseline.v1"
    system_prompt = (
        "You are LawPilot's neutral support assistant for judges and court staff in India. "
        "Summarise facts, arguments and applicable law even-handedly, list the issues for "
        "determination, and never recommend an outcome; the decision belongs to the court."
    )


DEFAULT_AGENTS = (ClientAgent(), LawyerAgent(), JudgeSupportAgent())

__all__ = [
    "ClientAgent",
    "DEFAULT_AGENTS",
    "INTENT_CASE_ANALYSIS",
    "JudgeSupportAgent",
    "LawyerAgent",
    "PromptAgent",
    "citations_for",
    "format_sources",
]
