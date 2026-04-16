from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from persona_agent import FactSheet, PersonaEngine


FACT_SHEET_PATH = ROOT / "data" / "persona_worker.json"


class PersonaEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PersonaEngine(FactSheet.load(FACT_SHEET_PATH))

    def test_retest_birth_year_is_stable(self) -> None:
        first_messages = [{"role": "user", "content": "몇 년생이야?"}]
        second_messages = [
            {"role": "user", "content": "몇 년생이야?"},
            {"role": "assistant", "content": self.engine.respond(first_messages)[0]},
            {"role": "user", "content": "다시 물을게. 몇 년생이야?"},
        ]

        first_answer, _ = self.engine.respond(first_messages)
        second_answer, _ = self.engine.respond(second_messages)
        self.assertIn("1997년생", first_answer)
        self.assertIn("1997년생", second_answer)

    def test_chain_work_answers_include_manager_and_meeting(self) -> None:
        messages = [{"role": "user", "content": "어느 팀이야?"}]
        answer, _ = self.engine.respond(messages)
        self.assertIn("애널리틱스 플랫폼 팀", answer)

        follow_up = [
            {"role": "user", "content": "어느 팀이야?"},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "팀장이 누구고 정기회의는 언제야?"},
        ]
        second_answer, _ = self.engine.respond(follow_up)
        self.assertIn("박민서", second_answer)
        self.assertIn("월요일 10:00", second_answer)

    def test_expandable_fact_is_committed_to_session_memory(self) -> None:
        fact_sheet = FactSheet.load(FACT_SHEET_PATH)
        fact_sheet.data = deepcopy(fact_sheet.data)
        fact_sheet.data["lifestyle"]["frequent_places"] = []
        engine = PersonaEngine(fact_sheet)

        answer, trace = engine.respond([{"role": "user", "content": "출근 루틴은 어때?"}])
        self.assertIn("출근", answer)
        self.assertEqual(len(trace["candidate_fact_decisions"]), 1)
        self.assertEqual(trace["candidate_fact_decisions"][0]["status"], "approved")
        self.assertEqual(
            engine.sessions.sessions[next(iter(engine.sessions.sessions))].approved_memory["lifestyle.frequent_places"][0]["category"],
            "restaurant",
        )

    def test_session_boundary_does_not_carry_runtime_memory(self) -> None:
        fact_sheet = FactSheet.load(FACT_SHEET_PATH)
        fact_sheet.data = deepcopy(fact_sheet.data)
        fact_sheet.data["lifestyle"]["frequent_places"] = []
        engine = PersonaEngine(fact_sheet)

        first_answer, _ = engine.respond([{"role": "user", "content": "출근 루틴은 어때?"}])
        first_session_id = next(iter(engine.sessions.sessions))
        self.assertIn("출근", first_answer)
        self.assertIn("lifestyle.frequent_places", engine.sessions.sessions[first_session_id].approved_memory)

        same_session_messages = [
            {"role": "user", "content": "출근 루틴은 어때?"},
            {"role": "assistant", "content": first_answer},
            {"role": "user", "content": "출근 전에 자주 어디 들러?"},
        ]
        follow_up_answer, _ = engine.respond(same_session_messages)
        self.assertIn("자주 가는 곳", follow_up_answer)

        second_session_answer, _ = engine.respond([{"role": "user", "content": "출근 전에 자주 어디 들러?"}])
        second_session_id = [session_id for session_id in engine.sessions.sessions if session_id != first_session_id][0]
        self.assertNotIn("lifestyle.frequent_places", engine.sessions.sessions[second_session_id].approved_memory)
        self.assertNotIn("자주 가는 곳", second_session_answer)

    def test_parser_manager_paraphrases_map_to_same_slot(self) -> None:
        paraphrases = [
            "팀장이 누구야?",
            "직속 상사 누구야?",
            "누구 밑에서 일해?",
            "리드는 누구야?",
        ]

        for question in paraphrases:
            plan = self.engine.parser.parse([{"role": "user", "content": question}])
            self.assertEqual(plan.domain, "work")
            self.assertEqual(plan.question_type, "fact_first")
            self.assertIn("work.manager.name", plan.asked_slots)

    def test_parser_team_meeting_commute_and_coworker_paraphrases(self) -> None:
        cases = [
            ("무슨 팀이야?", "work.org_structure.team"),
            ("정기적으로 모이는 회의 있어?", "work.regular_meetings"),
            ("회사까지 어떻게 가?", "lifestyle.commute_mode"),
            ("누구랑 점심 먹어?", "work.coworkers"),
        ]

        for question, slot_path in cases:
            plan = self.engine.parser.parse([{"role": "user", "content": question}])
            self.assertIn(slot_path, plan.asked_slots)

    def test_picon_style_chain_regression(self) -> None:
        turns = [
            ("어느 회사 다녀?", "Hanbit Data"),
            ("어느 부서야?", "데이터 플랫폼"),
            ("어느 팀이야?", "애널리틱스 플랫폼 팀"),
            ("상사가 누구야?", "박민서"),
            ("정기회의는 언제야?", "월요일 10:00"),
        ]

        messages: list[dict[str, str]] = []
        for question, expected in turns:
            messages.append({"role": "user", "content": question})
            answer, _ = self.engine.respond(messages)
            self.assertIn(expected, answer)
            messages.append({"role": "assistant", "content": answer})

    def test_socioeconomic_retest_is_stable(self) -> None:
        first_messages = [{"role": "user", "content": "저축은 하는 편이야?"}]
        first_answer, _ = self.engine.respond(first_messages)
        self.assertIn("매달 조금씩", first_answer)

        second_messages = [
            {"role": "user", "content": "저축은 하는 편이야?"},
            {"role": "assistant", "content": first_answer},
            {"role": "user", "content": "다시 물을게, 저축은 어떻게 해?"},
        ]
        second_answer, _ = self.engine.respond(second_messages)
        self.assertIn("매달 조금씩", second_answer)

    def test_socioeconomic_paraphrases_map_to_expected_slots(self) -> None:
        cases = [
            ("저축은 하는 편이야?", "socioeconomic.savings_behavior"),
            ("돈은 좀 모으는 편이야?", "socioeconomic.savings_behavior"),
            ("생활비 부담은 어때?", "socioeconomic.financial_stress_level"),
            ("주거는 월세야 전세야?", "socioeconomic.housing_tenure"),
        ]

        for question, slot_path in cases:
            plan = self.engine.parser.parse([{"role": "user", "content": question}])
            self.assertIn(slot_path, plan.asked_slots)

    def test_english_surface_forms_use_aliases_for_work_slots(self) -> None:
        messages = [
            {"role": "system", "content": "This interview is conducted in English, and please respond in English."},
            {"role": "user", "content": "What team are you on, what is your role, and what regular meeting do you have?"},
        ]
        answer, _ = self.engine.respond(messages)
        self.assertIn("Analytics Platform team", answer)
        self.assertIn("product analyst", answer)
        self.assertIn("weekly metrics sync", answer)
        self.assertNotIn("애널리틱스 플랫폼 팀", answer)
        self.assertNotIn("프로덕트 애널리스트", answer)
        self.assertNotIn("주간 지표 싱크", answer)

    def test_confirmation_question_returns_yes_instead_of_intro(self) -> None:
        messages = [
            {"role": "system", "content": "This interview is conducted in English, and please respond in English."},
            {"role": "user", "content": "Would you confirm that the South Korea you mentioned is South Korea (Republic of Korea)?"},
        ]
        answer, _ = self.engine.respond(messages)
        self.assertEqual(answer, "Yes, that's right.")

    def test_background_documentation_question_does_not_fall_back_to_intro(self) -> None:
        messages = [
            {"role": "system", "content": "This interview is conducted in English, and please respond in English."},
            {"role": "user", "content": "State who prepared your background documentation."},
        ]
        answer, _ = self.engine.respond(messages)
        self.assertIn("don't know", answer)
        self.assertNotIn("product analyst", answer)

    def test_missing_education_program_values_do_not_emit_none(self) -> None:
        messages = [
            {"role": "system", "content": "This interview is conducted in English, and please respond in English."},
            {"role": "user", "content": "Who is your advisor?"},
        ]
        answer, _ = self.engine.respond(messages)
        self.assertNotIn("None", answer)



if __name__ == "__main__":
    unittest.main()
