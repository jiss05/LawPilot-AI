"""
Request classification (SCRUM-21: "Requests are classified and routed correctly").

Two stages:
1. Keyword rules -- instant, no model call, always available.
2. If the rules are not confident, ask the model through the gateway for a
   JSON label. If the model is unavailable or answers nonsense, the rule
   result is used, so classification never fails a request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.llm.gateway import ModelGateway
from app.llm.types import ChatMessage, GenerationRequest, ModelError
from app.orchestration.state import (
    INTENT_CASE_ANALYSIS,
    INTENT_DOCUMENT_DRAFTING,
    INTENT_LEGAL_INFORMATION,
    INTENT_LEGAL_RESEARCH,
    INTENT_OUT_OF_SCOPE,
    INTENTS,
)

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT_VERSION = "classifier.v1"
CONFIDENT = 0.75


@dataclass(frozen=True)
class Classification:
    intent: str
    confidence: float
    classified_by: str  # "rules" | "model"


_RULES: list[tuple[str, float, re.Pattern]] = [
    (INTENT_DOCUMENT_DRAFTING, 0.9, re.compile(
        r"\b(draft|drafting|prepare|write)\b.{0,40}\b(notice|petition|plaint|affidavit|agreement|"
        r"contract|deed|application|complaint|reply|vakalat|bail application|legal notice|will)\b",
        re.I | re.S)),
    (INTENT_CASE_ANALYSIS, 0.85, re.compile(
        r"\b(judgment|judgement|bench (memo|note)|issues? for (determination|adjudication)|"
        r"ratio decidendi|obiter|summari[sz]e (the )?(arguments|submissions|case record)|"
        r"framing of issues|operative (part|portion)|order sheet)\b", re.I)),
    (INTENT_LEGAL_RESEARCH, 0.8, re.compile(
        r"\b(case law|precedents?|citations?|landmark|supreme court|high court|"
        r"held in|AIR \d{4}|SCC|section \d+|article \d+|sec\. ?\d+|interpretation of|"
        r"compare .* (act|section))\b", re.I)),
    (INTENT_LEGAL_INFORMATION, 0.7, re.compile(
        r"\b(my rights?|can i|am i|what (should|can) i do|is it legal|legal(ly)?|law|"
        r"police|fir|bail|divorce|custody|tenant|landlord|rent|consumer|property|"
        r"salary|employer|dowry|maintenance|cheque bounce|court|lawyer|advocate|"
        r"complaint|rights|act|ipc|bns|crpc|bnss|cpc)\b", re.I)),
]

_NON_LEGAL = re.compile(
    r"\b(recipe|cook|weather|cricket score|movie|song|lyrics|joke|python|javascript|"
    r"code|program|homework|math|poem|game)\b", re.I)


def classify_by_rules(message: str) -> Classification:
    for intent, confidence, pattern in _RULES:
        if pattern.search(message):
            return Classification(intent, confidence, "rules")
    if _NON_LEGAL.search(message):
        return Classification(INTENT_OUT_OF_SCOPE, 0.6, "rules")
    # Unknown: treat as a general legal question, low confidence.
    return Classification(INTENT_LEGAL_INFORMATION, 0.4, "rules")


_SYSTEM = (
    "You classify messages sent to an Indian legal assistant. "
    "Reply with JSON only: {\"intent\": <one of " + ", ".join(INTENTS) + ">, "
    "\"confidence\": <0 to 1>}. "
    "legal_information = a person asking what the law says or what their rights/options are. "
    "legal_research = finding statutes, sections, case law or precedents. "
    "document_drafting = writing a legal document (notice, petition, agreement...). "
    "case_analysis = analysing a judgment, case record, issues or arguments for a court. "
    "out_of_scope = anything that is not a legal question."
)


class RequestClassifier:
    def __init__(self, gateway: ModelGateway | None = None, *, use_model: bool = True) -> None:
        self.gateway = gateway
        self.use_model = use_model and gateway is not None

    def classify(self, message: str) -> Classification:
        rules = classify_by_rules(message)
        if rules.confidence >= CONFIDENT or not self.use_model:
            return rules
        try:
            data = self.gateway.generate_json(GenerationRequest(
                messages=[ChatMessage("system", _SYSTEM), ChatMessage("user", message[:2000])],
                prompt_version=CLASSIFIER_PROMPT_VERSION,
                temperature=0.0,
                max_output_tokens=60,
                purpose="classifier",
            ))
        except ModelError as exc:
            logger.info("Model classification unavailable (%s); using rules", exc.code)
            return rules
        intent = str(data.get("intent", "")).strip().lower()
        if intent not in INTENTS:
            return rules
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.6))))
        except (TypeError, ValueError):
            confidence = 0.6
        return Classification(intent, confidence, "model")
