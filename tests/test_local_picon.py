from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import requests


ROOT = Path(__file__).resolve().parents[1]
SERVER_PORT = 8011
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/v1/chat/completions"


def wait_for_server(url: str, timeout: int = 20) -> None:
    started = time.time()
    while time.time() - started < timeout:
        try:
            response = requests.get(url.replace("/v1/chat/completions", "/health"), timeout=1)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError("Server did not become ready in time.")


def direct_smoke_test() -> None:
    payload = {
        "model": "persona-agent",
        "messages": [
            {"role": "user", "content": "어느 회사 다니고 팀장은 누구야?"}
        ],
    }
    response = requests.post(SERVER_URL, json=payload, timeout=5)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    assert "Hanbit Data" in content
    assert "박민서" in content
    print("direct_smoke_test:", content)


def try_picon_run() -> None:
    try:
        import picon  # type: ignore
    except ImportError:
        print("picon package is not installed; skipping picon.run() test.")
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set; skipping picon.run() test.")
        return

    os.environ.setdefault("SERPER_API_KEY", "placeholder-serper-key")
    os.environ.setdefault("GOOGLE_GEOCODE", "placeholder-google-geocode")

    result = picon.run(
        persona="",
        api_base=f"http://127.0.0.1:{SERVER_PORT}/v1",
        name="PersonaAgent",
        num_turns=int(os.getenv("PICON_NUM_TURNS", "4")),
        num_sessions=int(os.getenv("PICON_NUM_SESSIONS", "1")),
        do_eval=os.getenv("PICON_DO_EVAL", "0") == "1",
        output_dir=str(ROOT / "tmp" / "picon_results"),
    )
    print("picon.run() finished:", json.dumps(result.summary, indent=2, default=str))


def main() -> int:
    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            str(ROOT / "template_server.py"),
            "--fact-sheet",
            str(ROOT / "data" / "persona_worker.json"),
            "--host",
            "127.0.0.1",
            "--port",
            str(SERVER_PORT),
            "--name",
            "PersonaAgent",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        preexec_fn=os.setsid,
    )

    try:
        wait_for_server(SERVER_URL)
        direct_smoke_test()
        try_picon_run()
        return 0
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        if proc.stdout:
            leftover = proc.stdout.read()
            if leftover.strip():
                print(leftover)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("This test harness uses environment variables: PICON_NUM_TURNS, PICON_NUM_SESSIONS, PICON_DO_EVAL.")
    raise SystemExit(main())
