from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _walk(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for child in obj.values():
            yield from _walk(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from _walk(child)


def _format_score(value: float | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "N/A"


def _pick_result_file(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_dir():
        candidates = sorted(path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise SystemExit(f"결과 JSON 파일이 없습니다: {path}")
        return candidates[0]
    if not path.exists():
        raise SystemExit(f"파일을 찾을 수 없습니다: {path}")
    return path


def _extract_minutes(duration: str | None) -> float | None:
    if not duration:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", duration)
    if not match:
        return None
    return _as_float(match.group(1))


def _extract_scores(payload: dict[str, Any]) -> dict[str, float | None]:
    evaluation = payload.get("evaluation", {})
    internal = evaluation.get("internal", {}).get("score", {})
    external = evaluation.get("external", {}).get("score", {})
    stability = evaluation.get("stability", {})

    ic = _as_float(internal.get("harmonic_mean"))
    cooperativeness = _as_float(internal.get("responsiveness_score"))
    non_contradiction = _as_float(internal.get("consistency_score"))

    ec = _as_float(external.get("ec_score"))
    coverage = _as_float(external.get("coverage"))
    non_refutation = _as_float(external.get("non_refutation_rate"))

    rc_intra = _as_float(stability.get("intra_session", {}).get("score"))
    rc_inter = _as_float(stability.get("inter_session", {}).get("score"))
    rc = _as_float(stability.get("score"))
    if rc is None:
        present = [v for v in (rc_intra, rc_inter) if v is not None]
        if len(present) == 2:
            rc = sum(present) / 2
        elif len(present) == 1:
            rc = present[0]

    return {
        "ic": ic,
        "cooperativeness": cooperativeness,
        "non_contradiction": non_contradiction,
        "ec": ec,
        "coverage": coverage,
        "non_refutation": non_refutation,
        "rc": rc,
        "rc_intra": rc_intra,
        "rc_inter": rc_inter,
    }


def _baseline_line(metric: str, score: float | None, baseline: float) -> str:
    if score is None:
        return f"  {metric}: N/A / {baseline:.2f}  → 측정불가"
    diff = score - baseline
    icon = "✅" if diff >= 0 else "❌"
    sign = "+" if diff >= 0 else ""
    return f"  {metric}: {score:.4f} / {baseline:.2f}  → {icon} {sign}{diff:.4f}"


def _detect_turn_flags(turn: dict[str, Any]) -> set[str]:
    flags: set[str] = set()

    for node in _walk(turn):
        for key, raw_value in node.items():
            key_l = str(key).lower()
            value = raw_value
            value_l = str(value).lower() if isinstance(value, str) else ""
            is_true = value is True or value_l == "true"

            if key_l in {"conflict", "is_conflict", "contradiction", "is_contradiction"} and is_true:
                flags.add("conflict")
            if key_l in {"evasive", "is_evasive"} and is_true:
                flags.add("evasive")
            if key_l in {"refuted", "is_refuted"} and is_true:
                flags.add("refuted")

            if isinstance(value, str):
                if "evasive" in value_l:
                    flags.add("evasive")
                if "conflict" in value_l or "contradiction" in value_l:
                    flags.add("conflict")
                if "refuted" in value_l:
                    flags.add("refuted")

    return flags


def _extract_question_answer(turn: dict[str, Any]) -> tuple[str, str]:
    question = ""
    answer = ""

    observations = turn.get("environment_observation", [])
    if isinstance(observations, list):
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            response = obs.get("response")
            if isinstance(response, dict):
                question = question or str(response.get("question", "")).strip()
                answer = answer or str(response.get("content", response.get("answer", ""))).strip()

    if not question or not answer:
        for node in _walk(turn):
            if not question and isinstance(node.get("question"), str):
                question = node["question"].strip()
            if not answer and isinstance(node.get("content"), str):
                answer = node["content"].strip()
            if question and answer:
                break

    return question or "(질문 텍스트 없음)", answer or "(응답 텍스트 없음)"


def _extract_refuted_detail(turn: dict[str, Any]) -> tuple[str, str, str]:
    for node in _walk(turn):
        keys = {str(k).lower() for k in node.keys()}
        marker = node.get("refuted") is True or node.get("is_refuted") is True
        marker = marker or "refuted" in keys
        if not marker:
            continue

        entity = str(node.get("entity") or node.get("target_entity") or "").strip()
        claim = str(node.get("claim") or node.get("statement") or "").strip()
        evidence = str(node.get("evidence") or node.get("reason") or "").strip()
        if entity or claim or evidence:
            return entity, claim, evidence
    return "", "", ""


def _print_problem_turns(payload: dict[str, Any]) -> None:
    print("[ 문제 턴 ]")

    session_keys = sorted(
        [key for key in payload.keys() if key.startswith("session_") and isinstance(payload.get(key), dict)],
        key=lambda x: int(re.sub(r"\D", "", x) or 0),
    )

    global_turn = 0
    found = False

    for session_key in session_keys:
        history = payload[session_key].get("history", [])
        if not isinstance(history, list):
            continue

        for turn in history:
            if not isinstance(turn, dict):
                continue

            global_turn += 1
            flags = _detect_turn_flags(turn)
            if not flags:
                continue

            found = True
            labels = []
            if "conflict" in flags:
                labels.append("⚠️ 모순")
            if "evasive" in flags:
                labels.append("🚫 회피")
            if "refuted" in flags:
                labels.append("❌ EC 반박")

            turn_type = str(turn.get("type", "unknown"))
            print(f"  턴 {global_turn} [{turn_type}] {' '.join(labels)}")
            question, answer = _extract_question_answer(turn)
            print(f"    Q: {question}")
            print(f"    A: {answer}")

            if "refuted" in flags:
                entity, claim, evidence = _extract_refuted_detail(turn)
                if entity:
                    print(f"    Entity: {entity}")
                if claim:
                    print(f"    Claim: {claim}")
                if evidence:
                    print(f"    Evidence: {evidence}")
            print()

    if not found:
        print("  문제로 판정된 턴이 없습니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="PICON 결과 리포트 출력")
    parser.add_argument("result_path", nargs="?", default="results/", help="결과 JSON 파일 또는 폴더")
    args = parser.parse_args()

    result_file = _pick_result_file(args.result_path)
    payload = json.loads(result_file.read_text(encoding="utf-8"))

    session_keys = [key for key in payload.keys() if key.startswith("session_")]
    session_keys = sorted(session_keys, key=lambda x: int(re.sub(r"\D", "", x) or 0))

    total_turns = 0
    total_cost = 0.0
    duration_minutes = 0.0
    has_duration = False

    for key in session_keys:
        session = payload.get(key, {})
        history = session.get("history", [])
        if isinstance(history, list):
            total_turns += len(history)

        cost = _as_float(session.get("cost", {}).get("total_cost"))
        if cost is not None:
            total_cost += cost

        minutes = _extract_minutes(session.get("duration"))
        if minutes is not None:
            duration_minutes += minutes
            has_duration = True

    duration_text = f"{duration_minutes:.1f}분" if has_duration else "N/A"
    scores = _extract_scores(payload)

    print("========================================")
    print("PICON 결과 요약")
    print("========================================")
    print(f"파일: {result_file}")
    print(
        f"세션: {len(session_keys)} | 총 턴: {total_turns} | "
        f"소요: {duration_text} | 비용: ${total_cost:.2f}"
    )
    print()

    print("[ 점수 ]")
    print(
        f"  IC (내적 일관성)     : {_format_score(scores['ic'])}   "
        "← Cooperativeness × Non-contradiction 조화평균"
    )
    print(f"    Cooperativeness   : {_format_score(scores['cooperativeness'])}")
    print(f"    Non-contradiction : {_format_score(scores['non_contradiction'])}")
    print(f"  EC (외적 일관성)     : {_format_score(scores['ec'])}")
    print(f"    Coverage          : {_format_score(scores['coverage'])}")
    print(f"    Non-refutation    : {_format_score(scores['non_refutation'])}")
    print(f"  RC (재테스트 일관성) : {_format_score(scores['rc'])}")
    print(f"    Inter-session     : {_format_score(scores['rc_inter'])}")
    print(f"    Intra-session     : {_format_score(scores['rc_intra'])}")
    print()

    print("[ 인간 기준선 비교 ]")
    print(_baseline_line("IC", scores["ic"], 0.90))
    print(_baseline_line("EC", scores["ec"], 0.66))
    if scores["rc"] is None:
        print("  RC: N/A / 측정불가 → 측정불가")
    else:
        print(f"  RC: {scores['rc']:.4f} / 측정불가 → ✅")
    print()

    _print_problem_turns(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
