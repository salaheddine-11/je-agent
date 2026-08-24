"""Run TRIAGE on an EXISTING run (does not re-ingest or re-create the run dir).

Fills in the missing LLM stage for runs started via the console (which only do
INGEST->CROSS_REF), saving llm/triage_report.json so the resume path can
narrate + finalize.

Usage: GEMINI_API_KEY=... uv run python scripts/triage_existing.py <run_dir>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import duckdb

from je_agent.config import load_config
from je_agent.llm.provider import OpenAICompatibleProvider
from je_agent.run_context import RunContext
from je_agent.store import RunStore
from je_agent.triage import run_triage
from je_agent.universe import select_universe


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: triage_existing.py <run_dir (under JEAGENT_RUNS_DIR)>")
        return 2
    run_dir = Path(sys.argv[1])
    ctx = RunContext(run_dir.parent if run_dir.name.isupper() else run_dir)
    # resolve: pass the actual run dir path (containing config.yaml + workspace.duckdb)
    if not (run_dir / "config.yaml").exists():
        candidates = [run_dir, run_dir / ".."]
        print(f"no config.yaml at {run_dir}")
        return 2
    config = load_config(run_dir / "config.yaml")
    store = RunStore(run_dir / "runstore.sqlite")
    con = duckdb.connect(str(run_dir / "workspace.duckdb"))

    key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("PILOT_MODEL", "gemini-3.5-flash-lite")
    provider = OpenAICompatibleProvider(
        base_url=os.environ.get("GEMINI_BASE_URL",
                                "https://generativelanguage.googleapis.com/v1beta/openai"),
        model=model, api_key=key)

    universe = select_universe(con, config)
    print(f"universe={universe.selected}/{universe.total_flagged} fallback={universe.fallback_used}")
    report = run_triage(con, config, provider, universe, store, config.run_id,
                        save_to=run_dir / "llm" / "triage_report.json")
    concerns, actions = {}, {}
    for a in report.assessments:
        concerns[a.rationale_concern] = concerns.get(a.rationale_concern, 0) + 1
        actions[a.recommended_action] = actions.get(a.recommended_action, 0) + 1
    print(f"triage: covered={report.universe_covered}/{universe.selected} "
          f"packs={len(report.pack_ids)} concern={json.dumps(concerns)} "
          f"action={json.dumps(actions)}")
    print(f"saved {run_dir / 'llm' / 'triage_report.json'}")
    store.close()
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
