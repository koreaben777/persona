from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from .fact_sheet import FactSheet
from .types import CandidateFactRecord, GeneratedClaim, QuestionPlan, SessionState, VerificationResult


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _matches_memory(claim_value: Any, memory_values: list[Any]) -> bool:
    if isinstance(claim_value, list):
        return _json_key(claim_value) == _json_key(memory_values)
    return _json_key(claim_value) in {_json_key(value) for value in memory_values}


class Verifier:
    def verify(
        self,
        fact_sheet: FactSheet,
        question_plan: QuestionPlan,
        answer_text: str,
        used_claims: list[GeneratedClaim],
        proposed_claims: list[GeneratedClaim],
        session: SessionState,
    ) -> VerificationResult:
        reasons: list[str] = []
        fact_conflict = False
        dialogue_conflict = False

        for claim in used_claims:
            if claim.slot_path.startswith("derived_facts."):
                continue
            memory_values = session.approved_memory.get(claim.slot_path, [])
            if memory_values:
                if not _matches_memory(claim.value, memory_values):
                    dialogue_conflict = True
                    reasons.append(f"Used claim conflicts with session memory: {claim.slot_path}")
                continue
            canonical = fact_sheet.get(claim.slot_path)
            if canonical is not None and canonical != claim.value and claim.claim_type == "existing":
                fact_conflict = True
                reasons.append(f"Claim conflicts with canonical fact: {claim.slot_path}")

        for claim in proposed_claims:
            memory_values = session.approved_memory.get(claim.slot_path, [])
            if memory_values and not _matches_memory(claim.value, memory_values):
                dialogue_conflict = True
                reasons.append(f"Claim conflicts with session memory: {claim.slot_path}")

        evasive = False
        if question_plan.question_type == "fact_first" and question_plan.asked_slots and not used_claims:
            evasive = True
            reasons.append("Direct factual question was not grounded on any slot.")
        if not answer_text.strip():
            evasive = True
            reasons.append("Empty answer.")

        new_claims = [
            {"slot_path": claim.slot_path, "value": claim.value, "reason": claim.reason}
            for claim in proposed_claims
        ]
        return VerificationResult(
            fact_conflict=fact_conflict,
            dialogue_conflict=dialogue_conflict,
            evasive=evasive,
            new_claims=new_claims,
            reasons=reasons,
        )


class CommitGate:
    def commit(
        self,
        fact_sheet: FactSheet,
        session: SessionState,
        verification: VerificationResult,
    ) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        allowed_slots = fact_sheet.allowed_expandable_slots()

        for claim in verification.new_claims:
            slot_path = claim["slot_path"]
            value = claim["value"]
            reason = claim.get("reason", "")
            status = "rejected"
            decision_reason = "Slot not allowed for expansion."

            if slot_path in allowed_slots:
                if self._looks_like_one_off(slot_path, value):
                    decision_reason = "One-off or opinion-like value cannot be stored."
                elif self._conflicts_with_canonical(fact_sheet, slot_path, value):
                    decision_reason = "Claim conflicts with canonical value."
                else:
                    canonical_count = fact_sheet.canonical_list_size(slot_path)
                    memory_values = session.approved_memory.get(slot_path, [])
                    max_items = fact_sheet.max_items_for(slot_path)
                    keys = {_json_key(item) for item in memory_values}
                    if _json_key(value) in keys:
                        status = "approved"
                        decision_reason = "Claim already present in session memory."
                    elif canonical_count + len(memory_values) >= max_items:
                        decision_reason = "Expandable slot already at max capacity."
                    else:
                        status = "approved"
                        decision_reason = "Approved into dialogue memory."
                        session.approved_memory.setdefault(slot_path, []).append(value)

            record = CandidateFactRecord(
                slot_path=slot_path,
                value=value,
                source_turn_id=f"turn-{session.turn_index}",
                status=status,
                reason=decision_reason if not reason else f"{decision_reason} {reason}".strip(),
            )
            session.candidate_facts.append(record)
            decisions.append(asdict(record))

        return decisions

    def _looks_like_one_off(self, slot_path: str, value: Any) -> bool:
        if isinstance(value, dict):
            flattened = " ".join(str(item) for item in value.values())
            return any(token in flattened for token in ["오늘", "today", "기분", "feeling"])
        return False

    def _conflicts_with_canonical(self, fact_sheet: FactSheet, slot_path: str, value: Any) -> bool:
        canonical = fact_sheet.get(slot_path)
        if not canonical:
            return False
        if isinstance(canonical, list):
            return False
        return canonical != value
