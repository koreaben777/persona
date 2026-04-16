from __future__ import annotations

from pathlib import Path

import template_server
from persona_agent import FactSheet, PersonaEngine


FACT_SHEET_PATH = Path(__file__).resolve().parent / 'data' / 'persona_worker.json'


if template_server.engine is None:
    fact_sheet = FactSheet.load(FACT_SHEET_PATH)
    template_server.engine = PersonaEngine(fact_sheet)
    template_server.agent_name = 'PersonaAgent'


app = template_server.app
