from __future__ import annotations

from dataclasses import asdict
import re

from .types import QuestionPlan


FACT_PATTERNS: list[tuple[re.Pattern[str], str, list[str]]] = [
    (re.compile(r"(몇\s*년생|birth year|year of birth|나이|몇살)", re.I), "identity", ["identity.birth_year", "derived_facts.computed_age"]),
    (re.compile(r"(born in the country|immigrant|이민자|태어난\s*나라)", re.I), "identity", ["identity.birth_place.country", "identity.current_residence.country"]),
    (re.compile(r"(이름|name)", re.I), "identity", ["identity.display_name"]),
    (re.compile(r"(어디 살아|사는 곳|거주|residence|live)", re.I), "identity", ["identity.current_residence"]),
    (re.compile(r"(language.*home|speak at home|집에서.*언어)", re.I), "identity", ["meta.language"]),
    (re.compile(r"(회사|직장|employer|company)", re.I), "work", ["work.current_employer.company_name"]),
    (re.compile(r"(field.*work|primary area.*work|분야)", re.I), "work", ["work.current_employer.industry"]),
    (re.compile(r"(부서|division|department)", re.I), "work", ["work.org_structure.department"]),
    (re.compile(r"(어느\s*팀|소속|소속\s*팀|어디\s*팀|무슨\s*팀|\bteam\b|팀(?!장))", re.I), "work", ["work.org_structure.team"]),
    (re.compile(r"(직급|직함|title|job|\brole\b)", re.I), "work", ["work.org_structure.job_title"]),
    (re.compile(r"(main activity|current main activity|main status|current main activity or status)", re.I), "work", ["work.employment_status", "work.org_structure.job_title"]),
    (re.compile(r"(상사|팀장|manager|boss|직속\s*상사|누구\s*밑에서|리드)", re.I), "work", ["work.manager.name", "work.manager.title"]),
    (re.compile(r"(회의|meeting|sync|싱크|정기적으로\s*모여|스탠드업)", re.I), "work", ["work.regular_meetings"]),
    (re.compile(r"(출근|commute|출근할\s*때|회사까지\s*어떻게|통근)", re.I), "lifestyle", ["lifestyle.commute_mode", "lifestyle.commute_description"]),
    (re.compile(r"(카페|자주 가는 곳|frequent place|coffee|어디 들러|어디 가|자주 어디)", re.I), "lifestyle", ["lifestyle.frequent_places"]),
    (re.compile(r"(점심|동료|coworker|colleague|누구랑\s*점심|같이\s*일하는\s*사람|주로\s*엮이는\s*동료)", re.I), "work", ["work.coworkers"]),
    (re.compile(r"(저축|\bsave money\b|\bsavings\b|돈은\s*좀\s*모으|돈\s*모으는\s*편)", re.I), "socioeconomic", ["socioeconomic.savings_behavior"]),
    (re.compile(r"(소득|\bincome\b|\bearnings\b|\bhousehold income\b)", re.I), "socioeconomic", ["socioeconomic.household_income_band"]),
    (re.compile(r"(월세|전세|\brent\b|\bhousing cost\b|\btenure\b|주거)", re.I), "socioeconomic", ["socioeconomic.housing_tenure"]),
    (re.compile(r"(돈\s*걱정|\bfinancial stress\b|\bliving cost\b|생활비\s*부담|재정\s*스트레스)", re.I), "socioeconomic", ["socioeconomic.financial_stress_level"]),
    (re.compile(r"(live with your parents|parents in law|부모님이랑\s*살아|동거)", re.I), "family", ["family.parents_cohabitation"]),
    (re.compile(r"(children|자녀)", re.I), "family", ["family.children_count"]),
    (re.compile(r"(가족|부모|형제|siblings|married|결혼)", re.I), "family", ["family"]),
    (re.compile(r"(religion|religious denomination|종교)", re.I), "lifestyle", ["lifestyle.religion.affiliation"]),
    (re.compile(r"(highest educational level|highest education|최종\s*학력)", re.I), "education", ["education.institutions"]),
    (re.compile(r"(학교|전공|교수|수업|course|advisor|class)", re.I), "education", ["education.current_program", "education.current_courses"]),
]

OPEN_ENDED_PATTERNS = [
    re.compile(r"(어때|어때요|요즘|바빠|힘들|좋아|느낌|설명|what.*like|how.*feel|how.*going)", re.I),
]

FOLLOWUPS_BY_DOMAIN = {
    "identity": ["identity.current_residence", "derived_facts.current_primary_role_label"],
    "work": ["work.current_employer.office_building", "work.regular_meetings", "work.main_responsibilities"],
    "education": ["education.current_courses", "education.current_program.advisor_name"],
    "family": ["family.partner", "family.children_count"],
    "lifestyle": ["lifestyle.frequent_places", "work.coworkers"],
    "socioeconomic": [
        "socioeconomic.savings_behavior",
        "socioeconomic.household_income_band",
        "socioeconomic.housing_tenure",
        "socioeconomic.financial_stress_level",
    ],
}


class QuestionParser:
    def parse(self, messages: list[dict[str, str]], known_terms: list[str] | None = None) -> QuestionPlan:
        question_text = self._extract_question(messages)
        asked_slots: list[str] = []
        domain = "identity"

        for pattern, candidate_domain, slots in FACT_PATTERNS:
            if pattern.search(question_text):
                if domain == "identity" or candidate_domain == "work":
                    domain = candidate_domain
                asked_slots.extend(slots)

        if known_terms:
            lowered = question_text.lower()
            for term in known_terms:
                if term and term.lower() in lowered:
                    if "work.coworkers" not in asked_slots:
                        asked_slots.append("work.coworkers")
                    domain = "work"

        asked_slots = list(dict.fromkeys(asked_slots))
        if (
            "lifestyle.commute_mode" in asked_slots
            and "work.current_employer.company_name" in asked_slots
            and not re.search(r"(어느\s*회사|무슨\s*회사|회사\s*이름)", question_text, re.I)
        ):
            asked_slots = [slot for slot in asked_slots if slot != "work.current_employer.company_name"]
        if "family.parents_cohabitation" in asked_slots and "identity.current_residence" in asked_slots:
            asked_slots = [slot for slot in asked_slots if slot != "identity.current_residence"]
        if not asked_slots:
            domain = self._infer_domain(question_text)

        question_type = "fact_first"
        if any(pattern.search(question_text) for pattern in OPEN_ENDED_PATTERNS):
            question_type = "draft_first"
        elif not asked_slots:
            question_type = "draft_first"

        likely_followups = FOLLOWUPS_BY_DOMAIN.get(domain, [])
        return QuestionPlan(
            domain=domain,
            question_type=question_type,
            asked_slots=asked_slots,
            likely_followups=likely_followups,
            question_text=question_text.strip(),
        )

    @staticmethod
    def as_dict(plan: QuestionPlan) -> dict[str, object]:
        return asdict(plan)

    def _infer_domain(self, question_text: str) -> str:
        lowered = question_text.lower()
        if any(token in lowered for token in ["회사", "팀", "상사", "출근", "work", "office"]):
            return "work"
        if any(token in lowered for token in ["학교", "수업", "교수", "class", "school"]):
            return "education"
        if any(token in lowered for token in ["가족", "부모", "형제", "family"]):
            return "family"
        if any(token in lowered for token in ["저축", "income", "rent", "생활비", "financial", "savings"]):
            return "socioeconomic"
        if any(token in lowered for token in ["취미", "주말", "카페", "루틴", "lifestyle", "weekend"]):
            return "lifestyle"
        return "identity"

    def _extract_question(self, messages: list[dict[str, str]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content", "")
        return ""
