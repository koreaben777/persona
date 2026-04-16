"""
PICON wrapping server with a deterministic persona engine.

This keeps the public API identical to the upstream template server:
    POST /v1/chat/completions

The difference is that generate_response() routes through a stateful
persona engine backed by a validated fact sheet, RAG documents, a verifier,
and a commit gate for expandable facts.
"""

from __future__ import annotations

import argparse
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from persona_agent import FactSheet, FactSheetError, PersonaEngine


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

LOGGER = logging.getLogger("template_server")
app = FastAPI()
engine: PersonaEngine | None = None
agent_name = "PersonaAgent"


def generate_response(messages: list[dict[str, str]]) -> str:
    if engine is None:
        raise RuntimeError("Persona engine is not initialized.")
    content, _trace = engine.respond(messages)
    return content


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": agent_name}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        return JSONResponse(status_code=400, content={"error": "No messages provided"})

    try:
        content = generate_response(messages)
    except FactSheetError as error:
        LOGGER.error("Fact sheet error: %s", error)
        return JSONResponse(status_code=500, content={"error": str(error)})
    except Exception as error:  # pragma: no cover - defensive path
        LOGGER.exception("Agent error")
        return JSONResponse(status_code=500, content={"error": str(error)})

    created = int(time.time())
    model = body.get("model") or agent_name
    return {
        "id": f"chatcmpl-{created}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PICON-compatible persona agent server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--fact-sheet",
        required=True,
        help="Path to a picon_fact_sheet_v2 JSON file.",
    )
    parser.add_argument(
        "--name",
        default="PersonaAgent",
        help="Agent name surfaced in the OpenAI-compatible response model field.",
    )
    return parser.parse_args()


def main() -> None:
    global engine
    global agent_name

    args = parse_args()
    fact_sheet = FactSheet.load(args.fact_sheet)
    engine = PersonaEngine(fact_sheet)
    agent_name = args.name or fact_sheet.get("identity.display_name", "PersonaAgent")

    LOGGER.info("Agent: %s", agent_name)
    LOGGER.info("Fact sheet: %s", args.fact_sheet)
    LOGGER.info("PICON endpoint: http://%s:%s/v1", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
