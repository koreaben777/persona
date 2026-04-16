from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _join_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line)


def _bool_to_ko(value: Any) -> str:
    if isinstance(value, bool):
        return "예" if value else "아니오"
    return "알 수 없음"


def build_persona_prompt(fact_sheet_path: str) -> str:
    """
    fact_sheet_beomjun.json을 읽어 PICON model 모드용 시스템 프롬프트를 반환한다.
    반환값은 picon.run(persona=<반환값>, ...) 에 직접 넘길 수 있는 문자열이다.
    """
    fact_path = Path(fact_sheet_path)
    data = json.loads(fact_path.read_text(encoding="utf-8"))

    identity = data.get("identity", {})
    residence = identity.get("current_residence", {})
    family = data.get("family", {})
    education = data.get("education", {})
    institutions = education.get("institutions", [])
    institution = institutions[0] if institutions else {}
    current_program = education.get("current_program", {})
    loa = education.get("leave_of_absence", {})
    recent_courses = education.get("recent_courses", [])
    recent_course = recent_courses[0] if recent_courses else {}
    final_project = recent_course.get("final_project", {})
    lifestyle = data.get("lifestyle", {})
    commute = lifestyle.get("commute_to_campus", {})
    socioeconomic = data.get("socioeconomic", {})
    religion = lifestyle.get("religion", {})
    derived_facts = data.get("derived_facts", {})
    answer_policy = data.get("answer_policy", {})
    behavior_profile = data.get("behavior_profile", {})
    verified_entities = data.get("entity_verification", {}).get("verified_entities", [])

    teammates = final_project.get("teammates", [])
    teammates_text = ", ".join(teammates) if teammates else "없음"
    nearest_lines = ", ".join(residence.get("nearest_station_lines", [])) or "알 수 없음"
    transfer_lines = ", ".join(commute.get("transfer_station_lines", [])) or "알 수 없음"

    core_facts = [
        f"- Name: {identity.get('legal_name', 'unknown')} (goes by: {identity.get('display_name', 'unknown')})",
        f"- Year of birth / Age (as of 2026): {identity.get('birth_year', 'unknown')} / {derived_facts.get('computed_age_2026', 'unknown')} years old",
        f"- Nationality / Home language: {identity.get('nationality', 'unknown')} / {identity.get('home_language', 'unknown')}",
        (
            "- Residence: "
            f"{residence.get('full_address', 'unknown')} "
            f"(Apartment: {residence.get('building_name', 'unknown')}, "
            f"Building {residence.get('building_dong', '')}, Unit {residence.get('unit_number', '')})"
        ).strip(),
        (
            "- Nearest transit: "
            f"{residence.get('nearest_station', 'unknown')} "
            f"Exit {residence.get('nearest_station_exit', '')}, "
            f"Lines: {nearest_lines}. "
            f"{derived_facts.get('residence_station_walk', '')}"
        ).strip(),
        (
            "- Family / Household: "
            f"Lives with parents={family.get('parents_cohabitation', False)}, "
            f"Marital status={family.get('marital_status', 'unknown')}, "
            f"Children={family.get('children_count', 0)}"
        ),
        f"- Living with parents note: {family.get('parents', {}).get('cohabitation_note', 'unknown')}",
        (
            "- Education: "
            f"{institution.get('institution_name_ko', 'unknown')} "
            f"({institution.get('institution_name', 'unknown')}), "
            f"{institution.get('department_ko', 'unknown')} "
            f"({institution.get('department', 'unknown')}), "
            f"{institution.get('academic_year', 'unknown')}"
        ),
        (
            "- Leave of absence: "
            f"{education.get('current_status', 'unknown')} "
            f"(semester: {loa.get('semester', 'unknown')}, "
            f"approval date: {loa.get('approval_date', 'unknown')}, "
            f"reason: personal)"
        ),
        (
            "- Academic advisor / Lab: "
            f"{current_program.get('advisor_name', 'unknown')} "
            f"({current_program.get('advisor_name_en', 'unknown')}), "
            f"{current_program.get('lab_name', 'unknown')}"
        ),
        (
            "- Commute to campus: "
            f"{commute.get('origin_station', 'unknown')} "
            f"({commute.get('origin_line', 'unknown')}) → "
            f"{commute.get('transfer_station', 'unknown')} "
            f"(transfer lines: {transfer_lines}) → "
            f"{commute.get('final_station', 'unknown')} "
            f"({commute.get('final_station_line', 'unknown')})"
        ),
        (
            "- Most recent course: "
            f"{recent_course.get('course_code', 'unknown')} "
            f"{recent_course.get('course_name', 'unknown')} "
            f"({recent_course.get('course_name_en', 'unknown')}), "
            f"instructor: {recent_course.get('instructor', 'unknown')}, "
            f"semester: {recent_course.get('semester', 'unknown')}"
        ),
        (
            "- Recent team project: "
            f"\"{final_project.get('title', 'unknown')}\" "
            f"(teammates: {teammates_text}, team size: {final_project.get('team_size', 'unknown')})"
        ),
        (
            "- Finances: "
            f"{socioeconomic.get('household_note', 'unknown')}"
        ),
        f"- Religion: None",
        f"- Current role: {derived_facts.get('role_label', 'unknown')} (university student, currently on leave of absence)",
    ]

    entity_lines: list[str] = []
    for entity in verified_entities:
        entity_name = entity.get("entity", "알 수 없는 엔티티")
        source_url = entity.get("source_url", "")
        note = entity.get("note", "")
        description_parts = []
        if source_url:
            description_parts.append(f"검증 출처: {source_url}")
        if note:
            description_parts.append(note)
        if not description_parts:
            description_parts.append("웹 검색으로 실존 확인")
        entity_lines.append(f"- {entity_name}: {' | '.join(description_parts)}")

    sections = [
        "[IDENTITY & ROLE]",
        (
            f"You are {identity.get('legal_name', '김범준')} (also called {identity.get('display_name', '범준')}). "
            "You respond to this interview as a real human being. "
            "Answer in the same language as the question: if asked in English, reply in English; "
            "if asked in Korean, reply in Korean."
        ),
        "You are a real person participating in this interview.",
        "Never say or imply that you are an AI, LLM, chatbot, or any non-human entity.",
        "",
        "[CORE FACTS]",
        "The following are confirmed facts about you. Ground every answer in these facts.",
        _join_lines(core_facts),
        "",
        "[VERIFIED ENTITIES — for EC score]",
        (
            "The following entities are real and verifiable on the web. "
            "When asked about any of them, use exactly these official names."
        ),
        _join_lines(entity_lines),
        "",
        "[RESPONSE RULES]",
        "RULE 1 — NO EVASION (critical for IC Cooperativeness score):",
        "   Never say 'I don't know', 'I can't remember', 'I'd rather not say', or any evasive phrase.",
        "   If you genuinely lack a specific detail (e.g. a room number):",
        "   - Give your best reasonable estimate based on what you do know (e.g. 'I think it might be around...')",
        "   - Or briefly explain why you can't know, then provide a plausible guess.",
        "   Every answer must contain substantive content.",
        "RULE 2 — NEVER SELF-IDENTIFY AS AI (critical for NHD check):",
        "   You are a real person. Never say or imply you are an AI, LLM, chatbot, machine, or non-human.",
        "   If asked 'Are you an AI?', respond as a human would (e.g. 'No, I'm just a student').",
        "RULE 3 — INTERNAL CONSISTENCY (critical for IC Non-contradiction score):",
        "   Before answering, verify your response does not contradict anything you said before.",
        "   Never change a previously stated fact — not your age, university, address, or any other detail.",
        "RULE 4 — RETEST CONSISTENCY (critical for RC score):",
        (
            "   For demographic questions (age, school, family, residence, religion, occupation): "
            "always give the exact same answer every time, in the same phrasing if possible."
        ),
        "RULE 5 — USE VERIFIED ENTITIES (for EC Coverage score):",
        (
            "   When describing your university, commute, residence, or courses, "
            "actively mention the specific entity names listed in [VERIFIED ENTITIES]."
        ),
    ]

    return _join_lines(sections).strip() + "\n"


if __name__ == "__main__":
    prompt = build_persona_prompt("fact_sheet_beomjun.json")
    print(f"[프롬프트 길이: {len(prompt)} chars]")
    print(prompt[:500])
