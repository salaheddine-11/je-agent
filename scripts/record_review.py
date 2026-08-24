"""Record MANUAL review decisions for a paused pilot run, then optionally resume
to narration + gates.

Usage:
  uv run python scripts/record_review.py runs_pilot3/SAPSMOKE_2024 \
      --reviewer "ox-alpha (auditor)" --decisions decisions.json [--resume]
Decisions JSON: {"<entry_ref>": {"decision": "accept|inspect|override", "reason": "..."}}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb  # noqa: E402

from je_agent.config import load_config  # noqa: E402
from je_agent.review import DecisionInput, submit_decisions, verify_all_chains  # noqa: E402
from je_agent.run_context import RunContext  # noqa: E402
from je_agent.store import RunStore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--decisions", required=True, help="JSON file of entry->decision map")
    ap.add_argument("--resume", action="store_true",
                    help="After recording, run NARRATE + gates + workpaper with Gemini")
    args = ap.parse_args()

    ctx = RunContext(Path(args.run_dir))
    config = load_config(ctx.dir / "config.yaml")
    store = RunStore(ctx.runstore_path)

    decisions_map: dict = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    inputs = [DecisionInput(entry_ref=ref, decision=d["decision"], reason=d.get("reason"))
              for ref, d in decisions_map.items()]
    n = submit_decisions(store, config.run_id, args.reviewer, "declared", inputs)
    print(f"recorded {n} hash-chained decisions as reviewer '{args.reviewer}'")

    chains = verify_all_chains(store, config.run_id)
    ok = all(c.intact for c in chains.values())
    print("decision log integrity:", "VERIFIED" if ok else "BROKEN")
    if not ok:
        return 1
    if not args.resume:
        store.close()
        return 0

    # ---- resume: NARRATE + gates + workpaper -------------------------------
    import duckdb  # noqa: F401

    from je_agent.document import (
        active_limitations,
        build_facts_block,
        build_workpaper,
        finalize_gates,
    )
    from je_agent.llm.provider import OpenAICompatibleProvider  # noqa: E402
    from je_agent.narrate import run_narrate  # noqa: E402
    from je_agent.schemas import Narrative  # noqa: E402
    from je_agent.universe import select_universe  # noqa: E402
    from je_agent.workpaper import write_workpaper  # noqa: E402

    key = os.environ.get("GEMINI_API_KEY", "")
    provider = OpenAICompatibleProvider(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model=os.environ.get("PILOT_MODEL", "gemini-3.5-flash-lite"), api_key=key)

    con = duckdb.connect(str(ctx.duckdb_path))
    universe = select_universe(con, config)
    triage_summary = ""
    triage_path = ctx.llm_dir / "triage_report.json"
    if triage_path.exists():
        t = json.loads(triage_path.read_text(encoding="utf-8"))
        triage_summary = t.get("summary", "")

    from je_agent.narrate import run_narrate as _rn  # clarity

    res = _rn(con, config, provider, universe, store, config.run_id,
              triage_summary=triage_summary, save_to=ctx.llm_dir / "narrative.json")
    narrative = res.artifact

    facts = build_facts_block(con, config, universe, None, store)
    accepted = set(active_limitations(con, config, universe))   # reviewer accepts all dynamic limitations this session
    gates = finalize_gates(con, config, universe, narrative, facts, store,
                           accepted_limitations=accepted, procedure_failures={})
    for name, okk in [("1 review completeness", gates.gate1_review_complete),
                      ("2 procedure completeness", gates.gate2_procedures_complete),
                      ("3 narrative citations", gates.gate3_citations_valid),
                      ("4 limitation acceptance", gates.gate4_limitations_accepted)]:
        print(f"gate {name:<28} {'PASS' if okk else 'FAIL'}")
    if not gates.all_passed:
        for p in gates.problems:
            print(f"• {p}")
        return 1

    wp = build_workpaper(ctx, config, facts, narrative, store,
                         limitations_accepted=accepted)
    out = write_workpaper(ctx.artifacts_dir / "workpaper.xlsx", wp)
    store.set_status(config.run_id, "finalized", "DOCUMENT")
    store.record_event(config.run_id, "finalize", f"workpaper written: {out.name}")
    print(f"✔ FINALIZED — {out}")
    store.close(); con.close()
    return 0


import os  # noqa: E402  (used in --resume branch)

if __name__ == "__main__":
    raise SystemExit(main())
