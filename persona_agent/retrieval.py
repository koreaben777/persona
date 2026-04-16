from __future__ import annotations

import re
from typing import Any

from .fact_sheet import FactSheet


TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text or "")}


def retrieve_slots(
    fact_sheet: FactSheet,
    session_memory: dict[str, list[Any]],
    asked_slots: list[str],
) -> dict[str, Any]:
    retrieved: dict[str, Any] = {}
    for slot_path in asked_slots:
        if slot_path in session_memory and session_memory[slot_path]:
            retrieved[slot_path] = list(session_memory[slot_path])
            continue
        retrieved[slot_path] = fact_sheet.get(slot_path)
    return retrieved


class RagRetriever:
    def __init__(self, fact_sheet: FactSheet):
        self.documents = fact_sheet.grounded_rag_documents()

    def search(
        self,
        query: str,
        asked_slots: list[str],
        domain: str | None = None,
        top_k: int = 2,
    ) -> list[dict[str, Any]]:
        query_tokens = tokenize(query)
        preferred_doc_types = {
            "work": {"work_context"},
            "education": {"school_context", "backstory"},
            "family": {"family_context", "backstory"},
            "lifestyle": {"routine_context", "hobby_context", "backstory"},
            "identity": {"backstory"},
        }.get(domain or "", set())
        scored: list[tuple[int, dict[str, Any]]] = []
        for doc in self.documents:
            doc_tokens = tokenize(doc.get("title", "")) | tokenize(doc.get("content", ""))
            overlap = len(query_tokens & doc_tokens)
            grounded_bonus = sum(3 for path in doc.get("grounded_slot_paths", []) if path in asked_slots)
            if preferred_doc_types and doc.get("doc_type") not in preferred_doc_types and grounded_bonus == 0:
                continue
            doc_type_bonus = 2 if doc.get("doc_type") in preferred_doc_types else 0
            if overlap or grounded_bonus:
                score = overlap + grounded_bonus + doc_type_bonus
                scored.append((score, doc))
            elif doc_type_bonus and not asked_slots:
                scored.append((doc_type_bonus, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]
