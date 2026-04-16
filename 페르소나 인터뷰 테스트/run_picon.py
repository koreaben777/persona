from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from persona_builder import build_persona_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PICON model-mode evaluation.")
    parser.add_argument("--model", default="gpt-4o", help="응답 모델")
    parser.add_argument("--turns", type=int, default=50, help="총 턴 수")
    parser.add_argument("--sessions", type=int, default=1, help="세션 수")
    parser.add_argument("--no-eval", action="store_true", help="평가 비활성화")
    parser.add_argument("--seed", type=int, default=42, help="질문 시드")
    return parser.parse_args()


def validate_env(do_eval: bool) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "Error: OPENAI_API_KEY is not set. "
            "Create a .env file with OPENAI_API_KEY=sk-..."
        )

    if do_eval and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise SystemExit(
            "Error: GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. "
            "Set one of them in .env when evaluation is enabled."
        )

    if not os.getenv("SERPER_API_KEY"):
        os.environ["SERPER_API_KEY"] = "placeholder"
        print(
            "Warning: SERPER_API_KEY is not set. "
            "Using placeholder, EC web verification may degrade.",
        )


def main() -> int:
    load_dotenv()
    args = parse_args()
    validate_env(do_eval=not args.no_eval)
    try:
        import picon
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Error: picon module is not installed. "
            "Run `pip install -r requirements.txt` first."
        ) from exc

    persona_prompt = build_persona_prompt("fact_sheet_beomjun.json")
    Path("results").mkdir(parents=True, exist_ok=True)

    result = picon.run(
        persona=persona_prompt,
        name="Beomjun",
        model=args.model,
        num_turns=args.turns,
        num_sessions=args.sessions,
        do_eval=not args.no_eval,
        output_dir="results",
        question_seed=args.seed,
        completion_kwargs={"temperature": 0},
    )

    print("\n=== PICON 결과 ===")
    print(f"성공: {result.success}")
    print(f"AI 감지: {result.ai_detected}")
    print(f"결과 파일: {result.result_path}")
    print()

    if result.eval_scores:
        print("--- 점수 ---")
        for key, value in result.eval_scores.items():
            print(f"  {key}: {value:.4f}" if isinstance(value, float) else f"  {key}: {value}")
    else:
        print("--- 점수 ---")
        print("  평가 점수가 없습니다. (--no-eval 또는 평가 실패 가능)")

    print()
    print(f"요약: {result.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
