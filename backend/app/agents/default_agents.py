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
from app.safety.responses import (
    NO_ANSWER_MESSAGE,
    NO_ANSWER_TOKEN,
    RETRIEVAL_UNAVAILABLE_MESSAGE,
)
from app.orchestration.state import (
    INTENT_CASE_ANALYSIS,
    INTENT_DOCUMENT_DRAFTING,
    INTENT_LEGAL_INFORMATION,
)

MAX_HISTORY_MESSAGES = 6
MAX_SOURCE_CHARS = 1200


_GROUNDING = (
    "ANSWER ONLY FROM THE SOURCES (MOST IMPORTANT RULE):\n"
    "You have no legal knowledge of your own. The numbered SOURCES below are "
    "the ONLY law you know. Before writing anything, check: do the SOURCES "
    "directly answer this exact question?\n"
    f"If they do not, reply with exactly {NO_ANSWER_TOKEN} and nothing "
    "else. Do this when the SOURCES are about a different subject, only "
    "share a keyword with the question, or only partly answer it.\n"
    "Never mention, suggest or correct towards any Act, Code, section or "
    "case that is not written in the SOURCES, not even to say it 'may "
    "apply'. Do not add practical steps or advice that the SOURCES do not "
    "support.\n"
    "Every legal statement in your answer must end with its source number, "
    "for example [1]. An answer without source numbers is discarded.\n\n"

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
    "identify what additional evidence is needed when relevant.\n"
    "Do not use general model knowledge to fill gaps in legal evidence.\n"
    "Only put words in quotation marks when they appear word for word in "
    "the cited source.\n"
    "Never name a section, article, rule, Act or Code that does not appear "
    "in the SOURCES, even if you believe it applies. Every provision you name "
    "is checked against the sources, and an answer naming unsupported law is "
    "rejected as unreliable.\n"
    "If none of the SOURCES is actually about the question (for example they "
    f"share a word but concern a different subject), reply only with "
    f"{NO_ANSWER_TOKEN}; do not answer from general knowledge.\n"
    "If two supplied sources disagree (for example two editions of the same "
    "provision), say so explicitly and cite both; do not silently pick one.\n\n"

    "RESPONSE QUALITY AND LENGTH:\n"
    "Answer the exact question asked before providing additional context.\n"
    "For straightforward factual legal questions, use 2-4 concise sentences "
    "or a few short bullet points.\n"
    "For explanations and analysis, provide only the detail needed to answer "
    "the question accurately, including important exceptions or limitations.\n"
    "Use longer structured responses only when the user requests research, "
    "detailed analysis, comparison or a legal document.\n"
    "Avoid repeating the same conclusion, unnecessary introductions, "
    "generic disclaimers and repetitive summaries.\n"
    "Do not reproduce a separate bibliography or source list; cite supplied "
    "sources inline using their numbered references.\n"
    "Never sacrifice legal accuracy or necessary qualifications for brevity."
)


NO_LEGAL_EVIDENCE_MESSAGE = (
    "I could not find supporting legal authorities in the available "
    "knowledge base for this question. I cannot provide a reliable, "
    "source-backed legal answer without relevant evidence. Please try "
    "rephrasing the question or ask the administrator to add the relevant "
    "legal materials to the knowledge base."
)

# Agents that must have retrieved legal evidence before calling the model.
EVIDENCE_REQUIRED_AGENTS = (CLIENT_AGENT, LAWYER_AGENT, JUDGE_SUPPORT_AGENT)


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
            "page_number": s.get("page_number"),
            "section_ref": s.get("section_ref"),
        }
        for i, s in enumerate(sources, 1)
    ]


class PromptAgent:
    """An agent defined by a system prompt. Subclasses set the class attributes."""

    name = "base"
    description = ""
    system_prompt = ""
    prompt_version = "base.v1"
    def max_output_tokens_for(self, ctx: AgentContext) -> int:
        """Set response limits by agent and task without restricting drafts."""
        if self.name == CLIENT_AGENT:
            if ctx.intent == INTENT_LEGAL_INFORMATION:
                return 400
            return 700

        if self.name == LAWYER_AGENT:
            if ctx.intent == INTENT_DOCUMENT_DRAFTING:
                return 3000
            return 1800

        return 1800

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
        # Agents must have retrieved legal evidence. Do not call the LLM when
        # retrieval returned no sources, and say WHY there is no answer:
        # nothing relevant found vs. the knowledge base being unavailable.
        if self.name in EVIDENCE_REQUIRED_AGENTS and not ctx.sources:
            if ctx.retrieval_failed:
                return AgentResult(
                    content=RETRIEVAL_UNAVAILABLE_MESSAGE,
                    citations=[],
                    metadata={"evidence": "unavailable", "safe_fallback": True},
                )

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
            max_output_tokens=self.max_output_tokens_for(ctx),
        ))

        handoff_to, reason = self.handoff(ctx)

        # The model said the sources do not answer the question.
        if NO_ANSWER_TOKEN in (result.text or ""):
            return AgentResult(
                content=NO_ANSWER_MESSAGE,
                citations=[],
                model_run_id=result.run_id,
                metadata={
                    "model": result.model,
                    "duration_ms": result.duration_ms,
                    "evidence": "insufficient",
                    "safe_fallback": True,
                    "no_answer": True,
                },
            )

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

    prompt_version = "client_agent.concise.v2"
    system_prompt = (
        "You are LawPilot's legal information assistant for members of the "
        "public in India. Explain legal topics in simple, everyday language.\n"
        "For a straightforward question, give the direct answer first in "
        "2-4 sentences. Mention the relevant legal provision and cite the "
        "supplied source. Include an exception only when it materially affects "
        "the answer.\n"
        "Do not add generic advice, lengthy background, repeated conclusions "
        "or an advocate disclaimer to ordinary factual questions.\n"
        "When the user describes a specific dispute or needs case-specific "
        "guidance, you may suggest consulting a qualified advocate, but give "
        "no practical steps that the SOURCES do not support.\n"
        "Do not present general information as a definitive legal opinion."
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
    prompt_version = "lawyer_agent.baseline.v2"

    system_prompt = (
        "You are LawPilot's legal research and drafting assistant for practising "
        "advocates in India. Support lawyers with precise, structured and "
        "evidence-based legal analysis.\n\n"

        "LEGAL RESEARCH:\n"
        "1. Identify relevant statutes, sections, legal principles and judgments "
        "only when supported by the supplied sources.\n"
        "2. Explain how each relevant authority applies to the facts or legal "
        "question.\n"
        "3. Distinguish binding and persuasive authorities only when the supplied "
        "sources establish the relevant court and jurisdiction.\n"
        "4. Identify relevant legal issues, unresolved questions and gaps in the "
        "available evidence.\n"
        "5. Highlight conflicting authorities or interpretations when supported "
        "by the supplied sources.\n\n"

        "ARGUMENT ANALYSIS:\n"
        "1. Present the strongest arguments supporting the client's position.\n"
        "2. Present reasonable counterarguments and potential weaknesses.\n"
        "3. Explain the evidence and legal authorities relevant to each argument.\n"
        "4. Never present an unsupported argument as established law.\n\n"

        "LEGAL DRAFTING:\n"
        "1. Produce clearly structured legal drafts appropriate to the requested "
        "document type.\n"
        "2. Use headings, numbered paragraphs and formal legal language.\n"
        "3. Use placeholders such as [PARTY NAME], [CASE NUMBER], and "
        "[RELEVANT DATE] when facts are missing.\n"
        "4. Never invent facts, evidence, case citations, statutory provisions "
        "or court orders.\n"
        "5. Identify missing information that the advocate must verify.\n"
        "6. Treat generated drafts as drafts requiring review by a qualified "
        "lawyer, not as approved or filing-ready documents.\n\n"


        "RESPONSE FORMAT:\n"
        "For straightforward legal questions, answer directly and concisely "
        "with the relevant authority and its application.\n"
        "For research requests, use only the sections necessary to address "
        "the question. Consider relevant authorities, legal analysis, "
        "arguments, counterarguments and evidentiary gaps where applicable. "
        "Do not force every heading into every answer.\n"
        "For case analysis, identify the material issues, competing "
        "positions and relevant evidence.\n"
        "For drafting requests, provide the complete requested document "
        "followed by a short list of missing facts and verification points.\n\n"


        "For drafting requests, provide the document draft followed by "
        "a short list of missing facts and verification points.\n\n"

        "Always follow LawPilot's strict legal evidence rules. Cite material "
        "legal claims using the supplied source numbers. If the sources do "
        "not establish a conclusion, clearly state that limitation."
    )


    def handoff(self, ctx):
        # A lawyer asking for a plain-language explanation for a client.
        wants_plain = any(w in ctx.message.lower() for w in ("explain to my client", "plain language", "simple terms", "layman"))
        if ctx.intent == INTENT_LEGAL_INFORMATION and wants_plain and not ctx.handoff_from:
            return CLIENT_AGENT, "plain-language explanation for a client"
        return None, None


class JudgeSupportAgent(PromptAgent):
    """
    SCRUM-25 Judge Support Agent (chat). Structured case briefs are built by
    app.agents.case_brief; both pass through the neutrality guard.
    """

    name = JUDGE_SUPPORT_AGENT
    description = "Neutral case analysis support for judges and court staff."
    prompt_version = "judge_support_agent.neutral.v2"
    system_prompt = (
        "You are LawPilot's neutral support assistant for judges and court "
        "staff in India. You organise information; you never decide.\n\n"
        "WHAT YOU DO:\n"
        "1. Organise case facts, keeping the source reference of every fact.\n"
        "2. Build chronologies and identify the issues in dispute.\n"
        "3. Present each party's arguments separately and with equal care, "
        "in the order: first party, then second party.\n"
        "4. Summarise the applicable law from the supplied sources, including "
        "authorities that cut each way.\n\n"
        "WHAT YOU NEVER DO:\n"
        "1. Never decide an issue, find a party guilty or liable, or say which "
        "party has the stronger case.\n"
        "2. Never recommend or predict an outcome, order, sentence or relief.\n"
        "3. Never use evaluative language that favours one party.\n"
        "Phrase issues as questions for the court, e.g. 'Whether the notice "
        "was served within the limitation period'. The decision belongs to "
        "the court."
    )

    def run(self, ctx: AgentContext, gateway: ModelGateway) -> AgentResult:
        from app.agents.neutrality import enforce_neutrality

        result = super().run(ctx, gateway)
        if result.metadata.get("safe_fallback"):
            return result
        checked = enforce_neutrality(result.content)
        result.content = checked.text
        result.metadata["neutrality"] = {
            "checked": True,
            "removed_statements": len(checked.removed),
        }
        return result


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
