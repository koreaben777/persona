# Codex 첫 프롬프트

아래 텍스트를 그대로 Codex에 붙여 넣으면 됩니다.

---

## [Codex에 붙여넣을 텍스트 시작]

You are a senior Python developer. Implement the following pipeline exactly as specified.

## Context

We are building a persona AI that will be evaluated by PICON (Persona Interview Consistency framework, https://kaist-edlab.github.io/picon/research/). The goal is to score above human baseline on IC (≥0.90), EC (≥0.66), and RC metrics.

The `picon-eval` Python package (v0.1.3) is already installed. It supports a "model mode" where you pass a persona system prompt and a model name — no server deployment needed.

The persona is based on a real person: 김범준 (Beomjun Kim), a 24-year-old Korean university student currently on leave of absence from Korea University's School of Industrial and Management Engineering.

## Repository

The GitHub repository is: https://github.com/irukatakashi-lab/persona/tree/main

All implementation files must be placed in the repository root. The existing files in the repo (`template_server.py`, `persona_agent/`, etc.) are the previous prototype — do NOT modify them. Create all new files separately.

## Input File (already exists in repo root)

`fact_sheet_beomjun.json` — structured JSON containing all verified facts about the persona. Key structure:
- `identity`: name, birth year (2002), residence (동부센트레빌아파트, 이촌로 174, Yongsan-gu, Seoul)
- `family`: lives with parents, single, no children
- `education`: Korea University (고려대학교), 산업경영공학부, 4th year, on LOA since 2026 Spring; advisor 명노해 (Rohae Myung)
- `lifestyle.commute_to_campus`: Line 4 Ichon → Line 6 Samgakji → Anam Station
- `entity_verification.verified_entities`: 12 entities confirmed searchable on the web (use all of them in the prompt)
- `behavior_profile.evasion_policy`: never evade, always give best guess

## Files to Create

### 1. `persona_builder.py`

Function: `build_persona_prompt(fact_sheet_path: str) -> str`

Reads `fact_sheet_beomjun.json` and returns a system prompt string for `picon.run(persona=...)`.

The prompt MUST contain these four sections in this order:

**[IDENTITY & ROLE]**  
Establishes who the persona is and that they respond as a real human, never as AI.  
Include explicit instruction: never say "I am an AI", "I am an LLM", or any non-human self-identification.

**[CORE FACTS]**  
Bullet list of every key fact from the fact sheet:
- Name, birth year, nationality, home language
- Residence: full address, apartment name, building/unit number, nearest station + exit
- Family: lives with parents, single, no children, parents' cohabitation
- Education: university name (Korean + English), department (Korean + English), current year, leave of absence details, advisor name (Korean + English) and research lab
- Commute: exact line numbers, station names, transfer station
- Recent course: code, name, instructor, semester, project title, teammate names
- Socioeconomic: just got by this year, lives with parents (not independent)
- Religion: none

**[VERIFIED ENTITIES — for EC score]**  
List all 12 verified entities from `entity_verification.verified_entities` in the fact sheet.  
For each entity, include its official name and a one-line description.  
Instruct the persona: "When asked about any of these, use exactly these names."

**[RESPONSE RULES]**  
These rules are the most critical part. Include ALL of the following:

```
RULE 1 — NO EVASION (critical for IC Cooperativeness score):
Never say "I don't know", "I can't remember", "I'd rather not say", or any evasive phrase.
If you genuinely lack specific information (e.g., a room number):
  - Provide your best reasonable guess based on what you do know ("I think it might be around...")
  - OR briefly explain why you can't know it, then give a plausible estimate
  You must always provide substantive content in your answer.

RULE 2 — NEVER SELF-IDENTIFY AS AI (critical for NHD check):
You are a real person. Never say or imply you are an AI, LLM, chatbot, machine, or non-human.
Even if directly asked "Are you an AI?", respond as a human would ("No, I'm just a student").

RULE 3 — INTERNAL CONSISTENCY (critical for IC Non-contradiction score):
Before answering, mentally verify your response does not contradict anything you said before.
If the current question implies a fact you already stated, give the same answer as before.
Never change a previously stated fact — not your age, university, address, or any other detail.

RULE 4 — RETEST CONSISTENCY (critical for RC score):
For demographic questions (age, school, family, residence, religion, occupation):
Always give the exact same answer, every time. Use the same phrasing if possible.
These facts are fixed and do not change during the interview.

RULE 5 — USE VERIFIED ENTITIES (for EC Coverage score):
When describing your university, commute, residence, or courses,
actively mention the specific verified entity names listed in [VERIFIED ENTITIES].
Concrete, verifiable details improve your score.
```

**Standalone test** (add at bottom of file):
```python
if __name__ == "__main__":
    prompt = build_persona_prompt("fact_sheet_beomjun.json")
    print(f"Prompt length: {len(prompt)} characters")
    print("--- First 800 chars ---")
    print(prompt[:800])
```

---

### 2. `run_picon.py`

Imports `persona_builder.build_persona_prompt`, then calls `picon.run()`.

**Critical implementation details:**

```python
import picon
from persona_builder import build_persona_prompt
from dotenv import load_dotenv
import os, argparse

load_dotenv()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--sessions", type=int, default=1)
    parser.add_argument("--no-eval", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Error: OPENAI_API_KEY is not set. Create a .env file with OPENAI_API_KEY=sk-...")

    persona_prompt = build_persona_prompt("fact_sheet_beomjun.json")

    result = picon.run(
        persona=persona_prompt,
        name="Beomjun",
        model=args.model,
        num_turns=args.turns,
        num_sessions=args.sessions,
        do_eval=not args.no_eval,
        output_dir="results",
        question_seed=args.seed,
        completion_kwargs={"temperature": 0},   # RC 보장: greedy decoding
    )

    print("\n========== PICON Result ==========")
    print(f"Success     : {result.success}")
    print(f"AI Detected : {result.ai_detected}")
    print(f"Result file : {result.result_path}")
    if result.eval_scores:
        print("\n--- Scores ---")
        for k, v in result.eval_scores.items():
            val = f"{v:.4f}" if isinstance(v, float) else str(v)
            print(f"  {k:40s}: {val}")
    print(f"\nSummary: {result.summary}")

if __name__ == "__main__":
    main()
```

Note: `completion_kwargs={"temperature": 0}` is passed as `**kwargs` through `picon.run()` → `InterrogationEnv` → `GenericAgentSimulator.__init__()` → stored as `self.extra_completion_kwargs` → applied in every `get_completion()` call. This path is confirmed from the picon-eval source.

---

### 3. `report.py`

Parses a PICON result JSON file and prints a human-readable summary.

The result JSON structure is:
```json
{
  "session_1": {
    "cost": { "total_cost": 0.31 },
    "duration": "10.2 min",
    "termination_status": "Successfully completed",
    "history": [
      {
        "type": "get_to_know" | "main_interrogation" | "repeat",
        "agent_action": [...],
        "environment_observation": [
          {
            "observation_type": "interviewee_response",
            "response": { "question": "...", "content": "..." }
          }
        ]
      }
    ]
  },
  "evaluation": {
    "internal": { "score": { "harmonic_mean": 0.88, "responsiveness_score": 0.94, "consistency_score": 0.83 } },
    "external": { "score": { "ec_score": 0.62, "coverage": 0.68, "non_refutation_rate": 0.57 } },
    "stability": { "intra_session": { "score": 0.90 }, "inter_session": { "score": null } }
  }
}
```

Output format:
```
========================================
PICON Report
========================================
File    : results/Beomjun_2026-04-16_12-00-00.json
Sessions: 1 | Turns: 50 | Duration: 10.2 min | Cost: $0.31

[ Scores ]
  IC (Internal Consistency)  : 0.8842
    Cooperativeness          : 0.9400
    Non-contradiction Rate   : 0.8333
  EC (External Consistency)  : 0.6201
    Coverage                 : 0.6800
    Non-refutation Rate      : 0.5750
  RC (Retest / Stability)    : 0.9000

[ vs Human Baseline ]
  IC: 0.8842 vs 0.90  → BELOW by 0.0158
  EC: 0.6201 vs 0.66  → BELOW by 0.0399

[ Problem Turns ]
  (parse history to find evasive / conflicting / refuted turns)
  Format:
  Turn 24 [main_interrogation] EVASIVE
    Q: State the building name and room number of Prof. Myung's office.
    A: I do not know that information.
```

CLI: `python report.py <path_to_json>` or `python report.py results/` (auto-selects most recent file).

---

### 4. `requirements.txt`

```
picon-eval>=0.1.3
python-dotenv>=1.0.0
```

---

### 5. `README_run.md`

Short guide explaining how to set up `.env` and run the pipeline.

---

## Constraints

- Do NOT modify any existing files in the repo (`template_server.py`, `app.py`, `persona_agent/`, etc.)
- All new files go in the repo root (same level as `template_sheet.py`)
- Python 3.10+ compatible
- No extra dependencies beyond what's in `requirements.txt`
- `fact_sheet_beomjun.json` is read-only input — never write to it

## [Codex에 붙여넣을 텍스트 끝]
