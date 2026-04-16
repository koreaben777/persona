# Codex 프롬프트 #2 — api_base 서버 통합 및 GitHub 배포

아래 텍스트를 그대로 Codex에 붙여 넣으세요.

---

## [Codex에 붙여넣을 텍스트 시작]

You are a senior Python developer. Continue working on the persona AI project in the repository https://github.com/irukatakashi-lab/persona/tree/main.

## Context

In the previous task you created these files (already in the repo root):
- `persona_builder.py` — builds a system prompt string from `fact_sheet_beomjun.json`
- `run_picon.py` — runs PICON in **model mode** (direct LLM call, no server needed)
- `report.py` — parses result JSON and prints scores
- `fact_sheet_beomjun.json` — persona data for 김범준 (Beomjun Kim)

The problem: **PICON model mode requires a GEMINI_API_KEY to run the Evaluator**, which we don't have. The only way to get official scores is to deploy a server to a public URL and let the PICON website evaluate it via `api_base` mode.

This task is to: **replace the existing `PersonaEngine` (rule-based) with a new LLM-based engine that uses `persona_builder.py`, and deploy it to GitHub so it can be evaluated at https://kaist-edlab.github.io/picon/research/**.

## Repository structure (current state)

```
persona/                          ← repo root
├── template_server.py            ← FastAPI server (DO NOT modify the API contract)
├── app.py                        ← Vercel entry point (imports from template_server)
├── api/index.py                  ← Vercel routing (DO NOT modify)
├── render.yaml                   ← Render deployment config
├── vercel.json                   ← Vercel deployment config
├── requirements.txt              ← fastapi, uvicorn, requests, picon-eval>=0.1.0
├── data/
│   └── persona_worker.json       ← OLD persona (do not delete, leave as-is)
├── persona_agent/                ← OLD rule-based engine (do not modify)
│   ├── engine.py
│   ├── fact_sheet.py
│   └── ...
├── fact_sheet_beomjun.json       ← NEW persona data (created in task #1)
├── persona_builder.py            ← NEW prompt builder (created in task #1)
├── run_picon.py                  ← NEW model-mode runner (created in task #1)
└── report.py                     ← NEW report printer (created in task #1)
```

## What to implement

### 1. `llm_server.py` — New LLM-based server (NEW FILE, repo root)

This is a **complete replacement** for the `template_server.py` engine logic.  
It must expose the **same API contract** as `template_server.py`:
- `GET /health` → `{"status": "ok", "agent": <name>}`
- `POST /v1/chat/completions` → OpenAI-compatible response

**How it works internally:**

```
Incoming POST /v1/chat/completions
  → Extract the last user message from messages[]
  → On first turn: build system prompt from persona_builder.build_persona_prompt()
  → Maintain full conversation history in memory (keyed by session_id)
  → Call OpenAI API (gpt-4o) with [system_prompt] + conversation_history + new_message
  → temperature=0  ← critical for RC score
  → Return the assistant response in OpenAI-compatible format
```

**Session management:**  
PICON sends a fresh conversation in each request — the `messages` array contains the full history so far.  
Do NOT use per-request state. Instead:
- Use the full `messages` list from the request body as the conversation history.
- **Always prepend the system prompt** (from `persona_builder`) as the first message before forwarding to OpenAI.
- This means every request is stateless from the server's perspective — just prepend the system prompt and forward.

**Concrete implementation:**

```python
from __future__ import annotations

import logging
import os
import time

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from persona_builder import build_persona_prompt

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
LOGGER = logging.getLogger("llm_server")

app = FastAPI()
AGENT_NAME = "Beomjun"
FACT_SHEET_PATH = "fact_sheet_beomjun.json"

# Build system prompt once at startup
_system_prompt: str | None = None

def get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        _system_prompt = build_persona_prompt(FACT_SHEET_PATH)
    return _system_prompt


@app.get("/health")
async def health():
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    if not messages:
        return JSONResponse(status_code=400, content={"error": "No messages provided"})

    # Strip any existing system message from the incoming history,
    # then prepend our own system prompt.
    non_system = [m for m in messages if m.get("role") != "system"]
    full_messages = [{"role": "system", "content": get_system_prompt()}] + non_system

    try:
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=full_messages,
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
    except Exception as e:
        LOGGER.exception("OpenAI call failed")
        return JSONResponse(status_code=500, content={"error": str(e)})

    created = int(time.time())
    return {
        "id": f"chatcmpl-{created}",
        "object": "chat.completion",
        "created": created,
        "model": AGENT_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

---

### 2. `app_llm.py` — Vercel entry point for the new server (NEW FILE, repo root)

Vercel needs a module-level `app` object. This file is the Vercel entry point for the new server.

```python
from llm_server import app
```

---

### 3. Update `vercel.json` — point Vercel to the new server

Replace the existing `vercel.json` with:

```json
{
  "version": 2,
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

And update `api/index.py` to:

```python
from app_llm import app
```

---

### 4. Update `render.yaml` — point Render to the new server

```yaml
services:
  - type: web
    name: persona-agent
    runtime: python
    rootDir: persona
    buildCommand: pip install -r requirements.txt
    startCommand: python llm_server.py
    healthCheckPath: /health
    envVars:
      - key: OPENAI_API_KEY
        sync: false
```

---

### 5. Update `requirements.txt` — merge old and new dependencies

```
fastapi==0.135.3
uvicorn==0.44.0
requests==2.33.1
picon-eval>=0.1.3
python-dotenv>=1.0.0
openai>=1.0.0
```

Note: `openai` package is required for the new `llm_server.py`. `picon-eval` version bumped to `>=0.1.3`.

---

## Constraints

- Do NOT modify `template_server.py`, `persona_agent/`, `data/persona_worker.json`, `api/index.py` structure (only change the import line inside it), `run_picon.py`, `report.py`, or `persona_builder.py`.
- The old server (`template_server.py` → `app.py`) must remain working — do not break it.
- New server entry point is `llm_server.py` → `app_llm.py`.
- Python 3.10+ compatible.
- All environment variables loaded via `python-dotenv` from `.env` file (for local) and from hosting platform env vars (for Render/Vercel).

## Verification steps (run after implementing)

```bash
# 1. Syntax check
python -m py_compile llm_server.py app_llm.py

# 2. Startup check (requires OPENAI_API_KEY in .env)
# python llm_server.py
# curl http://localhost:8002/health
# Expected: {"status": "ok", "agent": "Beomjun"}

# 3. Single-turn smoke test
# curl -s -X POST http://localhost:8002/v1/chat/completions \
#   -H "Content-Type: application/json" \
#   -d '{"messages": [{"role": "user", "content": "What is your year of birth?"}]}' \
#   | python -m json.tool
# Expected: response contains "2002"

# 4. System prompt injection check
# Verify that if messages already contains a system message, it gets stripped and replaced
```

## Important notes on PICON api_base mode

When PICON evaluates via `api_base`:
- It sends `POST /v1/chat/completions` with the full conversation history in `messages[]`
- The server must respond with an OpenAI-compatible JSON
- PICON does NOT send a system message — so the server must inject its own
- Each PICON request contains the complete conversation up to that turn
- The server is effectively **stateless** — just prepend the system prompt and call OpenAI

## [Codex에 붙여넣을 텍스트 끝]
