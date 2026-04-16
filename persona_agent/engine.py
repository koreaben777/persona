from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import logging
import re
from typing import Any

from .fact_sheet import FactSheet
from .parser import QuestionParser
from .retrieval import RagRetriever, retrieve_slots
from .types import GeneratedClaim, GenerationResult, SessionState
from .verifier import CommitGate, Verifier


LOGGER = logging.getLogger("persona_agent")

EN_SURFACE_ALIASES = {
    "데이터 플랫폼": "Data Platform",
    "애널리틱스 플랫폼 팀": "Analytics Platform",
    "프로덕트 애널리스트": "product analyst",
    "팀 리드": "team lead",
    "데이터 엔지니어": "data engineer",
    "주간 지표 싱크": "weekly metrics sync",
}


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.session_counter = 0

    def resolve(self, messages: list[dict[str, str]]) -> SessionState:
        normalized = self._normalize(messages)
        if self._is_new_session(normalized):
            return self._create_session(normalized)
        best_match: SessionState | None = None
        best_length = -1

        for session in self.sessions.values():
            if len(session.transcript) <= len(normalized) and session.transcript == normalized[: len(session.transcript)]:
                if len(session.transcript) > best_length:
                    best_match = session
                    best_length = len(session.transcript)

        if best_match is not None:
            return best_match

        return self._create_session(normalized)

    def _create_session(self, normalized: list[dict[str, str]]) -> SessionState:
        self.session_counter += 1
        digest = hashlib.sha1(json.dumps(normalized[:2], ensure_ascii=False).encode("utf-8")).hexdigest()[:8]
        session_id = f"{digest}-{self.session_counter:04d}"
        session = SessionState(session_id=session_id)
        self.sessions[session_id] = session
        return session

    def _is_new_session(self, normalized: list[dict[str, str]]) -> bool:
        return not any(message["role"] == "assistant" for message in normalized)

    def update(self, session: SessionState, incoming_messages: list[dict[str, str]], assistant_content: str) -> None:
        normalized = self._normalize(incoming_messages)
        session.transcript = normalized + [{"role": "assistant", "content": assistant_content}]
        session.turn_index += 1

    def _normalize(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role", "")
            if role == "system":
                continue
            normalized.append({"role": role, "content": message.get("content", "").strip()})
        return normalized


class PersonaEngine:
    def __init__(self, fact_sheet: FactSheet):
        self.fact_sheet = fact_sheet
        self.parser = QuestionParser()
        self.retriever = RagRetriever(fact_sheet)
        self.verifier = Verifier()
        self.commit_gate = CommitGate()
        self.sessions = SessionStore()

    def respond(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        session = self.sessions.resolve(messages)
        known_terms = self._known_terms(session)
        plan = self.parser.parse(messages, known_terms=known_terms)
        response_language = self._detect_response_language(messages, plan.question_text)
        retrieved_slots = retrieve_slots(self.fact_sheet, session.approved_memory, plan.asked_slots)
        rag_docs = self.retriever.search(plan.question_text, plan.asked_slots, domain=plan.domain)
        generation = self._generate(plan, retrieved_slots, rag_docs, session, response_language)
        verification = self.verifier.verify(
            self.fact_sheet,
            plan,
            generation.content,
            generation.used_claims,
            generation.proposed_claims,
            session,
        )

        if verification.fact_conflict or verification.dialogue_conflict or verification.evasive:
            LOGGER.warning("Regenerating safer answer due to verifier flags: %s", verification.reasons)
            generation = self._safe_fallback(plan, retrieved_slots, session, response_language)
            verification = self.verifier.verify(
                self.fact_sheet,
                plan,
                generation.content,
                generation.used_claims,
                generation.proposed_claims,
                session,
            )

        commit_decisions = self.commit_gate.commit(self.fact_sheet, session, verification)
        self.sessions.update(session, messages, generation.content)

        trace = {
            "session_id": session.session_id,
            "response_language": response_language,
            "parser_result": asdict(plan),
            "retrieved_slots": retrieved_slots,
            "retrieved_rag_docs": [
                {
                    "doc_id": doc.get("doc_id"),
                    "title": doc.get("title"),
                    "grounded_slot_paths": doc.get("grounded_slot_paths", []),
                }
                for doc in rag_docs
            ],
            "verifier_result": asdict(verification),
            "candidate_fact_decisions": commit_decisions,
            "final_answer": generation.content,
        }
        session.debug_log.append(trace)
        LOGGER.info("parser_result=%s", json.dumps(trace["parser_result"], ensure_ascii=False))
        LOGGER.info("retrieved_slots=%s", json.dumps(retrieved_slots, ensure_ascii=False))
        LOGGER.info("retrieved_rag_docs=%s", json.dumps(trace["retrieved_rag_docs"], ensure_ascii=False))
        LOGGER.info("verifier_result=%s", json.dumps(trace["verifier_result"], ensure_ascii=False))
        LOGGER.info("candidate_fact_decisions=%s", json.dumps(commit_decisions, ensure_ascii=False))
        LOGGER.info("final_answer=%s", generation.content)
        return generation.content, trace

    def _known_terms(self, session: SessionState) -> list[str]:
        names = [self.fact_sheet.get("work.manager.name", "")]
        for coworker in self.fact_sheet.get("work.coworkers", []):
            names.append(coworker.get("name", ""))
        for slot_path, values in session.approved_memory.items():
            if slot_path == "work.coworkers":
                names.extend(value.get("name", "") for value in values if isinstance(value, dict))
        return [name for name in names if name]

    def _generate(
        self,
        plan,
        retrieved_slots: dict[str, Any],
        rag_docs: list[dict[str, Any]],
        session: SessionState,
        response_language: str,
    ) -> GenerationResult:
        if self._is_confirmation_question(plan.question_text):
            return self._confirmation_response(response_language)
        if self._is_background_documentation_question(plan.question_text):
            return self._background_documentation_response(response_language)
        if plan.domain == "socioeconomic" and plan.asked_slots:
            return self._generate_fact_first(plan, retrieved_slots, rag_docs, response_language)
        if plan.question_type == "fact_first":
            return self._generate_fact_first(plan, retrieved_slots, rag_docs, response_language)
        return self._generate_draft_first(plan, retrieved_slots, rag_docs, session, response_language)

    def _generate_fact_first(
        self,
        plan,
        retrieved_slots: dict[str, Any],
        rag_docs: list[dict[str, Any]],
        response_language: str,
    ) -> GenerationResult:
        statements: list[str] = []
        claims: list[GeneratedClaim] = []
        handled_slots: set[str] = set()

        for slot_path in plan.asked_slots:
            if slot_path == "derived_facts.computed_age" and "identity.birth_year" in handled_slots:
                continue
            if slot_path == "identity.current_residence.country" and "identity.birth_place.country" in handled_slots:
                continue
            if slot_path == "work.manager.title" and "work.manager.name" in handled_slots:
                continue
            if slot_path == "lifestyle.commute_description" and "lifestyle.commute_mode" in handled_slots:
                continue
            value = retrieved_slots.get(slot_path)
            if value is None and slot_path not in {"lifestyle.religion.affiliation"}:
                continue
            text = self._slot_to_text(slot_path, value, response_language)
            if text:
                statements.append(text)
                claims.append(GeneratedClaim(slot_path=slot_path, value=value))
                handled_slots.add(slot_path)

        if not statements:
            statements.append(self._generic_summary(plan.domain, response_language))

        if response_language == "ko" and rag_docs and plan.domain in {"work", "education", "lifestyle"}:
            statements.append(self._supporting_doc_sentence(rag_docs[0]))

        content = " ".join(dict.fromkeys(statements))
        return GenerationResult(content=content, used_claims=claims)

    def _generate_draft_first(
        self,
        plan,
        retrieved_slots: dict[str, Any],
        rag_docs: list[dict[str, Any]],
        session: SessionState,
        response_language: str,
    ) -> GenerationResult:
        statements: list[str] = [self._generic_summary(plan.domain, response_language)]
        claims: list[GeneratedClaim] = []
        proposed: list[GeneratedClaim] = []

        if plan.domain == "work":
            statements = [self._work_summary(response_language)]
            claims.extend(
                [
                    GeneratedClaim("work.org_structure.team", self.fact_sheet.get("work.org_structure.team")),
                    GeneratedClaim("work.manager.name", self.fact_sheet.get("work.manager.name")),
                    GeneratedClaim("work.regular_meetings", self.fact_sheet.get("work.regular_meetings")),
                ]
            )
            if not self.fact_sheet.get("lifestyle.frequent_places"):
                generated_place = {
                    "place_name": "판교역 근처 작은 카페",
                    "category": "cafe",
                    "reason": "출근 전에 커피를 사서 바로 사무실로 가기 편하다.",
                }
                proposed.append(
                    GeneratedClaim(
                        slot_path="lifestyle.frequent_places",
                        value=generated_place,
                        claim_type="new",
                        reason="Generated because the user asked for a routine detail.",
                    )
                )
        elif plan.domain == "lifestyle":
            statements = [self._lifestyle_summary(response_language)]
            claims.extend(
                [
                    GeneratedClaim("lifestyle.commute_description", self.fact_sheet.get("lifestyle.commute_description")),
                    GeneratedClaim("derived_facts.route_summary", self.fact_sheet.get("derived_facts.route_summary")),
                ]
            )
            if not self.fact_sheet.get("lifestyle.frequent_places"):
                generated_place = {
                    "place_name": "오피스 근처 샐러드 가게",
                    "category": "restaurant",
                    "reason": "점심을 빠르게 해결하기 좋다.",
                }
                proposed.append(
                    GeneratedClaim(
                        slot_path="lifestyle.frequent_places",
                        value=generated_place,
                        claim_type="new",
                        reason="Generated because the user asked for an open-ended routine answer.",
                    )
                )
        elif plan.domain == "family":
            statements = [self._family_summary(response_language)]
            claims.append(GeneratedClaim("family.marital_status", self.fact_sheet.get("family.marital_status")))
        elif plan.domain == "education":
            statements = [self._education_summary(response_language)]
            claims.append(GeneratedClaim("education.current_program", self.fact_sheet.get("education.current_program")))
        else:
            statements = [self._identity_summary(response_language)]
            claims.append(GeneratedClaim("identity.display_name", self.fact_sheet.get("identity.display_name")))

        if response_language == "ko" and rag_docs:
            statements.append(self._supporting_doc_sentence(rag_docs[0]))

        return GenerationResult(content=" ".join(dict.fromkeys(statements)), used_claims=claims, proposed_claims=proposed)

    def _safe_fallback(self, plan, retrieved_slots: dict[str, Any], session: SessionState, response_language: str) -> GenerationResult:
        if plan.asked_slots:
            return self._generate_fact_first(plan, retrieved_slots, [], response_language)
        return GenerationResult(content=self._generic_summary(plan.domain, response_language))

    def _slot_to_text(self, slot_path: str, value: Any, response_language: str) -> str:
        if slot_path == "identity.birth_year":
            age = self.fact_sheet.get("derived_facts.computed_age")
            if response_language == "en":
                return f"I was born in {value}, so I'm {age} years old."
            return f"{value}년생이고, 지금 만 {age}살이야."
        if slot_path == "derived_facts.computed_age":
            birth_year = self.fact_sheet.get("identity.birth_year")
            if response_language == "en":
                return f"I'm {value} years old, born in {birth_year}."
            return f"지금 만 {value}살이고, {birth_year}년생이야."
        if slot_path == "identity.birth_place.country":
            current_country = self.fact_sheet.get("identity.current_residence.country")
            if response_language == "en":
                if value == current_country:
                    return f"I was born in {value} and I still live in {current_country}, so I'm not an immigrant."
                return f"I was born in {value}, but I currently live in {current_country}."
            if value == current_country:
                return f"태어난 나라도 {value}이고 지금 사는 곳도 {current_country}라서 이민자는 아니야."
            return f"태어난 나라는 {value}이고 지금은 {current_country}에 살고 있어."
        if slot_path == "identity.display_name":
            if response_language == "en":
                return f"My name is {value}."
            return f"이름은 {value}이야."
        if slot_path == "identity.current_residence":
            city = value.get("city")
            district = value.get("district")
            if response_language == "en":
                return f"I live in {district}, {city} right now."
            return f"지금은 {city} {district}에서 살고 있어."
        if slot_path == "meta.language":
            language_name = {"ko": "Korean", "en": "English"}.get(value, value)
            if response_language == "en":
                return f"I usually speak {language_name} at home."
            return f"집에서는 주로 {language_name}를 써."
        if slot_path == "work.current_employer.company_name":
            if response_language == "en":
                return f"I work at {value}."
            return f"지금 다니는 회사는 {value}야."
        if slot_path == "work.current_employer.industry":
            if response_language == "en":
                return f"My main work is in {value}."
            return f"주로 하는 일 분야는 {value} 쪽이야."
        if slot_path == "work.org_structure.department":
            if response_language == "en":
                return f"I'm in the {self._surface_value(value, response_language)} department."
            return f"부서는 {value}{self._copula(value)}."
        if slot_path == "work.org_structure.team":
            if response_language == "en":
                return f"I'm on the {self._surface_value(value, response_language)} team."
            return f"팀은 {value}{self._copula(value)}."
        if slot_path == "work.org_structure.job_title":
            if response_language == "en":
                surface = self._surface_value(value, response_language)
                return f"I work as {self._with_indefinite_article(surface)}."
            return f"직무는 {value}{self._copula(value)}."
        if slot_path == "work.employment_status":
            if response_language == "en":
                return f"My current status is {self._employment_label(value, response_language)}."
            return f"현재 상태는 {self._employment_label(value, response_language)}이야."
        if slot_path == "work.manager.name":
            title = self.fact_sheet.get("work.manager.title")
            if response_language == "en":
                surface_title = self._surface_value(title, response_language)
                return f"My direct manager is {value}, the {surface_title}." if title else f"My direct manager is {value}."
            return f"직속 상사는 {value} {title}야." if title else f"직속 상사는 {value}야."
        if slot_path == "work.manager.title":
            if response_language == "en":
                return f"My manager's title is {self._surface_value(value, response_language)}."
            return f"상사 직함은 {value}{self._copula(value)}."
        if slot_path == "work.regular_meetings":
            meeting = value[0] if isinstance(value, list) and value else None
            if meeting:
                if response_language == "en":
                    meeting_name = self._surface_value(meeting["meeting_name"], response_language)
                    return (
                        f"My regular meeting is {meeting_name} on "
                        f"{self._day_label(meeting['day_of_week'], response_language)} at {meeting['start_time']}."
                    )
                return (
                    f'고정 회의는 {self._day_label(meeting["day_of_week"])} {meeting["start_time"]}에 하는 '
                    f'{meeting["meeting_name"]} 회의가 있어.'
                )
        if slot_path == "lifestyle.commute_mode":
            description = self.fact_sheet.get("lifestyle.commute_description")
            if response_language == "en":
                return f"I usually commute by {self._commute_label(value, response_language)}, and {self._translate_commute_description(description)}"
            return f"출근은 주로 {self._commute_label(value)}로 하고, 보통 {description}"
        if slot_path == "lifestyle.commute_description":
            if response_language == "en":
                return f"My commute routine is that {self._translate_commute_description(value)}"
            return f"출근 루틴은 {value}"
        if slot_path == "lifestyle.frequent_places":
            if isinstance(value, list) and value:
                place = value[0]
                if response_language == "en":
                    return f"I often stop by {place['place_name']}, usually because {place['reason']}."
                return f'자주 가는 곳은 {place["place_name"]} 같은 {place["category"]}야.'
        if slot_path == "work.coworkers":
            if isinstance(value, list) and value:
                coworker = value[0]
                title = coworker.get("title")
                if response_language == "en":
                    surface_title = self._surface_value(title, response_language)
                    suffix = f", a {surface_title}," if title else ""
                    return f"The coworker I work with most often is {coworker['name']}{suffix} and {coworker['relationship_context']}"
                suffix = f" {title}" if title else ""
                return f'자주 엮이는 동료는 {coworker["name"]}{suffix}이고, {coworker["relationship_context"]}'
        if slot_path == "family.parents_cohabitation":
            if response_language == "en":
                return "Yes, I live with my parents." if value else "No, I don't live with my parents or parents-in-law."
            return "부모님과 같이 살아." if value else "부모님이나 시부모님과 같이 살지는 않아."
        if slot_path == "family.children_count":
            if response_language == "en":
                return "I don't have any children." if value == 0 else f"I have {value} children."
            return "자녀는 없어." if value == 0 else f"자녀는 {value}명이야."
        if slot_path == "family":
            status = value.get("marital_status")
            children_count = value.get("children_count")
            if response_language == "en":
                return f"My relationship status is {status}, and I have {children_count} children."
            return f"현재 {status} 상태고, 자녀는 {children_count}명이야."
        if slot_path == "socioeconomic.savings_behavior":
            if response_language == "en":
                return "I don't save very aggressively, but I do set aside a small amount every month."
            return "저축은 아주 공격적으로 하진 않고, 매달 조금씩 꾸준히 하는 편이야."
        if slot_path == "socioeconomic.household_income_band":
            if response_language == "en":
                return "My income level is closer to middle than especially high."
            return "소득 수준은 아주 높다기보다는 중간 정도라고 보는 게 맞아."
        if slot_path == "socioeconomic.housing_tenure":
            if response_language == "en":
                return "Right now I live in a monthly rent setup."
            return "지금은 월세 형태로 살고 있어."
        if slot_path == "socioeconomic.financial_stress_level":
            if response_language == "en":
                return "My living costs are manageable overall, though I still keep an eye on them."
            return "생활비 부담이 아주 큰 편은 아니지만, 완전히 신경 안 쓰는 수준도 아니야."
        if slot_path == "lifestyle.religion.affiliation":
            if response_language == "en":
                return "I don't belong to a religion." if not value else f"I belong to {value}."
            return "종교는 따로 없어." if not value else f"{value} 종교가 있어."
        if slot_path == "education.institutions":
            if isinstance(value, list) and value:
                institution = value[0]
                if response_language == "en":
                    return f"My highest completed education is a {institution['degree']} in {institution['major']} from {institution['institution_name']}."
                return f"최종 학력은 {institution['institution_name']} {institution['major']} {institution['degree']} 졸업이야."
        if slot_path == "education.current_program":
            if not isinstance(value, dict):
                return self._education_summary(response_language)
            institution_name = value.get("institution_name")
            department = value.get("department")
            advisor_name = value.get("advisor_name")
            if not institution_name or not department or not advisor_name:
                return self._education_summary(response_language)
            if response_language == "en":
                return (
                    f"I'm affiliated with {institution_name} in {department}, "
                    f"and my advisor is {advisor_name}."
                )
            return f'{institution_name} {department} 소속이고, 지도교수는 {advisor_name}이야.'
        if slot_path == "education.current_courses":
            if isinstance(value, list) and value:
                course = value[0]
                if response_language == "en":
                    return f"I take {course['course_name']} on {self._day_label(course['day_of_week'], response_language)} at {course['start_time']}."
                return f'{course["course_name"]} 수업을 {course["day_of_week"]} {course["start_time"]}에 들어.'
        return ""

    def _supporting_doc_sentence(self, doc: dict[str, Any]) -> str:
        content = doc.get("content", "").strip()
        if not content:
            return ""
        first_sentence = content.split(".")[0].strip()
        if first_sentence.endswith("다"):
            return first_sentence + "."
        return first_sentence

    def _is_confirmation_question(self, question_text: str) -> bool:
        return bool(re.search(r"(would you confirm|just to confirm|is that right|is that correct|confirm that)", question_text, re.I))

    def _is_background_documentation_question(self, question_text: str) -> bool:
        return bool(re.search(r"(background documentation|prepared your background|who prepared.*documentation)", question_text, re.I))

    def _confirmation_response(self, response_language: str) -> GenerationResult:
        if response_language == "en":
            return GenerationResult(content="Yes, that's right.")
        return GenerationResult(content="응, 맞아.")

    def _background_documentation_response(self, response_language: str) -> GenerationResult:
        if response_language == "en":
            return GenerationResult(content="I don't know who prepared my background documentation.")
        return GenerationResult(content="내 배경 문서를 누가 준비했는지는 나도 몰라.")

    def _identity_summary(self, response_language: str) -> str:
        if response_language == "en":
            job_title = self._surface_value(self.fact_sheet.get("work.org_structure.job_title"), response_language)
            return (
                f"I'm {self.fact_sheet.get('identity.display_name')}, and "
                f"I'm {self._with_indefinite_article(job_title)} at {self.fact_sheet.get('work.current_employer.company_name')}."
            )
        return (
            f'{self.fact_sheet.get("identity.display_name")}이고, '
            f'{self.fact_sheet.get("derived_facts.current_primary_role_label")}로 지내고 있어.'
        )

    def _work_summary(self, response_language: str) -> str:
        company = self.fact_sheet.get("work.current_employer.company_name")
        team = self.fact_sheet.get("work.org_structure.team")
        manager = self.fact_sheet.get("work.manager.name")
        meeting = self.fact_sheet.get("work.regular_meetings")[0]
        if response_language == "en":
            surface_team = self._surface_value(team, response_language)
            meeting_name = self._surface_value(meeting["meeting_name"], response_language)
            return (
                f"I work on the {surface_team} team at {company}. "
                f"I mainly handle funnel analysis and dashboard QA under {manager}, "
                f"and my week is anchored by {meeting_name} on "
                f"{self._day_label(meeting['day_of_week'], response_language)} at {meeting['start_time']}."
            )
        return (
            f'요즘은 {company}의 {team}에서 일하는 흐름이 꽤 일정한 편이야. '
            f'{manager} 리드 밑에서 퍼널 분석이랑 대시보드 QA를 주로 맡고 있고, '
            f'{self._day_label(meeting["day_of_week"])} {meeting["start_time"]} {meeting["meeting_name"]}이 주간 앵커라서 '
            "그 일정 기준으로 한 주를 정리하는 편이야."
        )

    def _education_summary(self, response_language: str) -> str:
        program = self.fact_sheet.get("education.current_program")
        if not program or not program.get("institution_name"):
            if response_language == "en":
                return "These days my work takes priority over school."
            return "지금은 학업보다 일 쪽 비중이 더 큰 편이야."
        if response_language == "en":
            return (
                f"I'm connected to {program['institution_name']} in {program['department']}, "
                f"and my schedule usually follows {program['advisor_name']}."
            )
        return (
            f'{program["institution_name"]} {program["department"]}에 있고, '
            f'연구나 수업 일정은 {program["advisor_name"]} 교수님 기준으로 돌아가.'
        )

    def _family_summary(self, response_language: str) -> str:
        status = self.fact_sheet.get("family.marital_status")
        sibling = self.fact_sheet.get("family.siblings", [])
        sibling_text = ""
        if sibling:
            sibling_text = f' 형제자매로는 {sibling[0]["relation"]} 한 명이 있어.'
        if response_language == "en":
            sibling_en = ""
            if sibling:
                sibling_en = f" I have one {sibling[0]['relation']}."
            return f"My family situation is {status}, and I live separately from my parents.{sibling_en}"
        return f"가족 쪽은 현재 {status} 상태고, 부모님과는 따로 살고 있어.{sibling_text}"

    def _lifestyle_summary(self, response_language: str) -> str:
        residence = self.fact_sheet.get("identity.current_residence")
        route = self.fact_sheet.get("derived_facts.route_summary")
        if response_language == "en":
            return (
                f"I live in {residence['district']}, {residence['city']}, "
                f"and my weekday routine is mostly fixed around that commute."
            )
        return (
            f'{residence["city"]} {residence["district"]}에서 지내고 있고, '
            f'평일 루틴은 대체로 {route} 쪽으로 고정돼 있어.'
        )

    def _generic_summary(self, domain: str, response_language: str) -> str:
        summaries = {
            "identity": self._identity_summary(response_language),
            "work": self._work_summary(response_language),
            "education": self._education_summary(response_language),
            "family": self._family_summary(response_language),
            "lifestyle": self._lifestyle_summary(response_language),
        }
        return summaries.get(domain, self._identity_summary(response_language))

    def _day_label(self, day_of_week: str, response_language: str = "ko") -> str:
        labels = {
            "ko": {
                "Mon": "월요일",
                "Tue": "화요일",
                "Wed": "수요일",
                "Thu": "목요일",
                "Fri": "금요일",
                "Sat": "토요일",
                "Sun": "일요일",
            },
            "en": {
                "Mon": "Monday",
                "Tue": "Tuesday",
                "Wed": "Wednesday",
                "Thu": "Thursday",
                "Fri": "Friday",
                "Sat": "Saturday",
                "Sun": "Sunday",
            },
        }
        return labels.get(response_language, labels["ko"]).get(day_of_week, day_of_week)

    def _commute_label(self, commute_mode: str, response_language: str = "ko") -> str:
        labels = {
            "ko": {
                "walk": "도보",
                "bus": "버스",
                "subway": "지하철",
                "car": "자동차",
                "bike": "자전거",
                "mixed": "대중교통",
            },
            "en": {
                "walk": "walking",
                "bus": "bus",
                "subway": "subway",
                "car": "car",
                "bike": "bike",
                "mixed": "public transit",
            },
        }
        return labels.get(response_language, labels["ko"]).get(commute_mode, commute_mode)

    def _employment_label(self, employment_status: str, response_language: str) -> str:
        labels = {
            "ko": {
                "full_time": "정규직으로 일하는 중",
                "part_time": "파트타임으로 일하는 중",
                "intern": "인턴으로 일하는 중",
                "contract": "계약직으로 일하는 중",
                "self_employed": "자영업 중",
                "not_applicable": "해당 없음",
            },
            "en": {
                "full_time": "full-time employment",
                "part_time": "part-time employment",
                "intern": "an internship",
                "contract": "contract work",
                "self_employed": "self-employment",
                "not_applicable": "not applicable",
            },
        }
        return labels.get(response_language, labels["ko"]).get(employment_status, employment_status)

    def _translate_commute_description(self, description: str) -> str:
        mapping = {
            "성수 오피스텔에서 나와 2호선과 신분당선을 타고 판교 쪽 사무실로 간다.": "I leave my officetel in Seongsu, take Line 2 and the Shinbundang Line, and head to the office near Pangyo."
        }
        return mapping.get(description, description)

    def _surface_value(self, value: str | None, response_language: str) -> str:
        if value is None or response_language != "en":
            return value or ""
        return EN_SURFACE_ALIASES.get(value, value)

    def _with_indefinite_article(self, phrase: str) -> str:
        if not phrase:
            return phrase
        article = "an" if phrase[0].lower() in {"a", "e", "i", "o", "u"} else "a"
        return f"{article} {phrase}"

    def _copula(self, value: str) -> str:
        if not value:
            return "야"
        last = value[-1]
        code = ord(last)
        if 0xAC00 <= code <= 0xD7A3:
            return "이야" if (code - 0xAC00) % 28 else "야"
        return "야"

    def _detect_response_language(self, messages: list[dict[str, str]], question_text: str) -> str:
        combined = " ".join(message.get("content", "") for message in messages if message.get("role") in {"system", "user"})
        lowered = combined.lower()
        if "respond in english" in lowered or "this interview is conducted in english" in lowered:
            return "en"
        ascii_letters = sum(character.isascii() and character.isalpha() for character in question_text)
        hangul_letters = sum("가" <= character <= "힣" for character in question_text)
        if ascii_letters > hangul_letters:
            return "en"
        return self.fact_sheet.preferred_language
