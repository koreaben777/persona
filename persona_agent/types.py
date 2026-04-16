from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class QuestionPlan:
    domain: str
    question_type: str
    asked_slots: list[str]
    likely_followups: list[str]
    question_text: str


@dataclass(slots=True)
class GeneratedClaim:
    slot_path: str
    value: Any
    claim_type: str = "existing"
    reason: str = ""


@dataclass(slots=True)
class GenerationResult:
    content: str
    used_claims: list[GeneratedClaim] = field(default_factory=list)
    proposed_claims: list[GeneratedClaim] = field(default_factory=list)


@dataclass(slots=True)
class VerificationResult:
    fact_conflict: bool
    dialogue_conflict: bool
    evasive: bool
    new_claims: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateFactRecord:
    slot_path: str
    value: Any
    source_turn_id: str
    status: str
    reason: str


@dataclass(slots=True)
class SessionState:
    session_id: str
    transcript: list[dict[str, str]] = field(default_factory=list)
    approved_memory: dict[str, list[Any]] = field(default_factory=dict)
    candidate_facts: list[CandidateFactRecord] = field(default_factory=list)
    turn_index: int = 0
    debug_log: list[dict[str, Any]] = field(default_factory=list)
