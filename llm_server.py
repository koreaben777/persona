from __future__ import annotations

import importlib.util
import logging
import os
import time
from pathlib import Path
from typing import Any

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from persona_builder import build_persona_prompt
except ModuleNotFoundError:
    # Fallback for environments where persona_builder.py is under a subdirectory.
    _fallback_builder = (
        Path(__file__).resolve().parent / "페르소나 인터뷰 테스트" / "persona_builder.py"
    )
    _spec = importlib.util.spec_from_file_location("persona_builder_fallback", _fallback_builder)
    if _spec is None or _spec.loader is None:
        raise
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    build_persona_prompt = _module.build_persona_prompt


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
LOGGER = logging.getLogger("llm_server")

app = FastAPI()
AGENT_NAME = "Beomjun"
ROOT_DIR = Path(__file__).resolve().parent
PRIMARY_FACT_SHEET = ROOT_DIR / "fact_sheet_beomjun.json"
FALLBACK_FACT_SHEET = ROOT_DIR / "페르소나 인터뷰 테스트" / "fact_sheet_beomjun.json"

# Build system prompt once at startup.
_system_prompt: str | None = None


def _resolve_fact_sheet_path() -> Path:
    if PRIMARY_FACT_SHEET.exists():
        return PRIMARY_FACT_SHEET
    return FALLBACK_FACT_SHEET


def get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        fact_sheet_path = _resolve_fact_sheet_path()
        _system_prompt = build_persona_prompt(str(fact_sheet_path))
    return _system_prompt


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    body = await request.json()
    messages = body.get("messages", [])

    if not isinstance(messages, list) or not messages:
        return JSONResponse(status_code=400, content={"error": "No messages provided"})

    # Strip any incoming system message and prepend our own persona system prompt.
    non_system = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    full_messages = [{"role": "system", "content": get_system_prompt()}] + non_system

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEY is not set"})

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=full_messages,
            temperature=0,
        )

        content = response.choices[0].message.content or ""
        content = content.strip()
    except Exception as exc:
        LOGGER.exception("OpenAI call failed")
        return JSONResponse(status_code=500, content={"error": str(exc)})

    created = int(time.time())
    usage = getattr(response, "usage", None)

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
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        },
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8002))
    uvicorn.run(app, host="0.0.0.0", port=port)
