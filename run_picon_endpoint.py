from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys


DEFAULT_ENDPOINT = "https://persona-jinsikkims-projects.vercel.app/v1"
DEFAULT_NAME = "MaengMaengbot"
ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
LOCAL_ENV_FILE = ROOT / ".picon.env"


def ensure_project_python() -> None:
    if not VENV_PYTHON.exists():
        return
    current = Path(sys.executable).resolve()
    target = VENV_PYTHON.resolve()
    if current == target:
        return
    os.execv(str(target), [str(target), str(Path(__file__).resolve()), *sys.argv[1:]])


def import_project_picon():
    site_packages = sorted((ROOT / ".venv" / "lib").glob("python*/site-packages"))
    if not site_packages:
        raise RuntimeError(f"Could not find project site-packages under {ROOT / '.venv' / 'lib'}")
    site_path = str(site_packages[0])
    if site_path not in sys.path:
        sys.path.insert(0, site_path)
    sys.modules.pop("picon", None)
    return importlib.import_module("picon")


def load_local_env() -> None:
    if not LOCAL_ENV_FILE.exists():
        return
    for raw_line in LOCAL_ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run PICon against an OpenAI-compatible endpoint and print the live interview logs."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="OpenAI-compatible api_base URL.")
    parser.add_argument("--name", default=DEFAULT_NAME, help="Agent name shown in PICon logs.")
    parser.add_argument("--turns", type=int, default=50, help="Number of interview turns.")
    parser.add_argument("--sessions", type=int, default=1, help="Number of interview sessions.")
    parser.add_argument(
        "--do-eval",
        action="store_true",
        help="Run evaluator after interview generation. Leave off if evaluator keys are not configured.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "tmp" / "picon_results"),
        help="Directory where PICon will write interview results.",
    )
    parser.add_argument(
        "--persona",
        default="",
        help="Optional persona string. Leave empty when using external endpoint mode.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="OpenAI API key for PICon's questioner/extractor/evaluator models. Defaults to OPENAI_API_KEY.",
    )
    return parser


def ensure_required_env(args: argparse.Namespace) -> None:
    if args.openai_api_key:
        os.environ["OPENAI_API_KEY"] = args.openai_api_key
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is required because PICon uses OpenAI models for the interviewer/extractor. "
            "Set the environment variable or pass --openai-api-key."
        )
    os.environ.setdefault("SERPER_API_KEY", "placeholder-serper-key")
    os.environ.setdefault("GOOGLE_GEOCODE", "placeholder-google-geocode")



def main() -> int:
    ensure_project_python()
    load_local_env()
    picon = import_project_picon()

    args = build_parser().parse_args()
    ensure_required_env(args)

    result = picon.run(
        persona=args.persona,
        api_base=args.endpoint,
        name=args.name,
        num_turns=args.turns,
        num_sessions=args.sessions,
        do_eval=args.do_eval,
        output_dir=args.output_dir,
    )

    print()
    print("PICon summary:")
    print(json.dumps(result.summary, indent=2, default=str))
    result_path = getattr(result, "result_path", None) or getattr(result, "output_path", None)
    if result_path:
        print(f"Result path: {result_path}")
    else:
        print("Result path: <not provided by installed picon version>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
