from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any


class FactSheetError(ValueError):
    pass


VALID_PRIMARY_ROLES = {"student", "worker", "student_worker"}
VALID_PROFILE_TYPES = {"student", "worker", "student_worker"}

CORE_REQUIRED_BASE = [
    "identity.legal_name",
    "identity.display_name",
    "identity.birth_year",
    "identity.birth_place.country",
    "identity.birth_place.city",
    "identity.current_residence.country",
    "identity.current_residence.city",
    "family.marital_status",
]

CORE_REQUIRED_BY_ROLE = {
    "worker": [
        "work.current_employer.company_name",
        "work.org_structure.team",
        "work.org_structure.job_title",
        "work.manager.name",
        "work.regular_meetings",
    ],
    "student": [
        "education.current_program.institution_name",
        "education.current_program.department",
        "education.current_program.advisor_name",
        "education.current_courses",
    ],
    "student_worker": [
        "work.current_employer.company_name",
        "work.org_structure.team",
        "work.manager.name",
        "education.current_program.institution_name",
        "education.current_program.advisor_name",
    ],
}


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for token in path.split("."):
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    current = data
    parts = path.split(".")
    for token in parts[:-1]:
        current = current.setdefault(token, {})
    current[parts[-1]] = value


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class FactSheet:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "FactSheet":
        file_path = Path(path)
        with file_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        sheet = cls(path=file_path, data=data)
        sheet.validate()
        sheet.compute_derived_facts()
        return sheet

    @property
    def persona_id(self) -> str:
        return str(self.data["persona_id"])

    @property
    def preferred_language(self) -> str:
        return str(self.data["answer_policy"]["preferred_language"])

    def validate(self) -> None:
        schema_version = self.data.get("schema_version")
        if schema_version != "picon_fact_sheet_v2":
            raise FactSheetError(f"Unsupported schema_version: {schema_version}")

        meta = self.data.get("meta", {})
        profile_type = meta.get("profile_type")
        primary_role = meta.get("primary_role")
        if profile_type not in VALID_PROFILE_TYPES:
            raise FactSheetError(f"Invalid profile_type: {profile_type}")
        if primary_role not in VALID_PRIMARY_ROLES:
            raise FactSheetError(f"Invalid primary_role: {primary_role}")

        required_paths = list(CORE_REQUIRED_BASE)
        required_paths.extend(CORE_REQUIRED_BY_ROLE.get(primary_role, []))
        missing = [path for path in required_paths if not _has_meaningful_value(_get_path(self.data, path))]
        if missing:
            missing_text = ", ".join(missing)
            raise FactSheetError(f"Missing required core facts: {missing_text}")

        expandable = self.data.get("expandable_slots", {})
        allowed_paths = expandable.get("allowed_slot_paths", [])
        max_items = expandable.get("max_items_per_slot_path", {})
        for slot_path, limit in max_items.items():
            if slot_path not in allowed_paths:
                raise FactSheetError(f"Expandable slot has max_items but is not allowed: {slot_path}")
            if not isinstance(limit, int) or limit <= 0:
                raise FactSheetError(f"Invalid max_items value for {slot_path}: {limit}")

        for path in allowed_paths:
            if _get_path(self.data, path) is None:
                raise FactSheetError(f"Expandable slot path does not exist in fact sheet: {path}")

        for doc in self.data.get("rag_documents", []):
            for path in doc.get("grounded_slot_paths", []):
                if _get_path(self.data, path) is None and path not in allowed_paths:
                    raise FactSheetError(f"RAG document references unknown slot path: {path}")

        self.data.setdefault("candidate_facts", [])
        self.data.setdefault("derived_facts", {})
        self.data.setdefault("updated_at", _iso_now())

    def compute_derived_facts(self, today: date | None = None) -> None:
        today = today or date.today()
        birth_year = self.data["identity"]["birth_year"]
        birth_month = self.data["identity"].get("birth_month", 1)
        computed_age = today.year - birth_year
        if today.month < birth_month:
            computed_age -= 1

        meta = self.data["meta"]
        work = self.data.get("work", {})
        education = self.data.get("education", {})
        lifestyle = self.data.get("lifestyle", {})

        if meta["primary_role"] == "worker":
            role_label = f'{work["org_structure"]["job_title"]} at {work["current_employer"]["company_name"]}'
        elif meta["primary_role"] == "student":
            role_label = f'{education["current_status"]} student at {education["current_program"]["institution_name"]}'
        else:
            role_label = "student_worker"

        anchors: list[str] = []
        for meeting in work.get("regular_meetings", []):
            anchors.append(
                f'{meeting["day_of_week"]} {meeting["start_time"]} {meeting["meeting_name"]}'
            )
        for course in education.get("current_courses", []):
            anchors.append(
                f'{course["day_of_week"]} {course["start_time"]} {course["course_name"]}'
            )

        route_summary = lifestyle.get("commute_description") or lifestyle.get("commute_mode", "")
        derived = self.data.setdefault("derived_facts", {})
        derived["computed_age"] = computed_age
        derived["current_primary_role_label"] = role_label
        derived["route_summary"] = route_summary
        derived["weekly_anchor_summary"] = ", ".join(anchors[:3])

    def get(self, slot_path: str, default: Any = None) -> Any:
        value = _get_path(self.data, slot_path)
        return default if value is None else value

    def set(self, slot_path: str, value: Any) -> None:
        _set_path(self.data, slot_path, value)

    def allowed_expandable_slots(self) -> set[str]:
        return set(self.data["expandable_slots"]["allowed_slot_paths"])

    def max_items_for(self, slot_path: str) -> int:
        return int(self.data["expandable_slots"]["max_items_per_slot_path"].get(slot_path, 0))

    def slot_exists(self, slot_path: str) -> bool:
        return _get_path(self.data, slot_path) is not None

    def grounded_rag_documents(self) -> list[dict[str, Any]]:
        return list(self.data.get("rag_documents", []))

    def canonical_list_size(self, slot_path: str) -> int:
        value = self.get(slot_path, [])
        return len(value) if isinstance(value, list) else 0
