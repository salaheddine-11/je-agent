"""Real-model TRIAGE smoke: run Gemini over the top-ranked SAP flagged entries.

Usage:
  GEMINI_API_KEY=... uv run python scripts/run_real_triage_smoke.py \
      --config sap_smoke_config.yaml --extract sap_pilot_extract.csv \
      --base-url https://generativelanguage.googleapis.com/v1beta/openai \
      --model gemini-3.6-flash

Prints the merged TriageReport summary + per-entry verdicts. Everything lands in
the run store (llm_outputs) exactly as production would.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb  # noqa: E402

from je_agent.config import load_config  # noqa: E402
from je_agent.crossref import cross_reference_flags  # noqa: E402
from je_agent.ingest import ingest_extract  # noqa: E402
from je_agent.llm.provider import OpenAICompatibleProvider  # noqa: E402
from je_agent.run_context import RunContext  # noqa: E402
from je_agent.rules import execute_rules  # noqa: E402
from je_agent.store import RunStore  # noqa: E402
from je_agent.triage import run_triage  # noqa: E402
from je_agent.universe import select_universe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--extract", required=True)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--base-url", default="https://generativelanguage.googleapis.com/v1beta/openai")
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--api-key-env", default="GEMINI_API_KEY")
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env)
    if not key:
        print(f"ERROR: set {args.api_key_env} env var", file=sys.stderr)
        return 2

    config = load_config(Path(args.config))
    ctx = RunContext.create(
        Path(args.runs_dir), config.run_id,
        Path(args.config).read_text(encoding="utf-8"),
        Path(args.extract),
    )
    store = RunStore(ctx.runstore_path)
    store.record_run(config.run_id, "smoke", "0.1.0",
                     config.model_dump(mode="json"), model_id=f"gemini/{args.model}")

    print("── deterministic stages ──────────────────────────────")
    rep = ingest_extract(ctx, config)
    print(f"INGEST   canonical={rep.canonical_rows} rejects={rep.rejected_rows}")
    con = duckdb.connect(str(ctx.duckdb_path))
    results = execute_rules(con, config)
    for r in results:
        ok = type(r).__name__ == "RuleResult"
        print(f"EXECUTE  {r.rule:<26} {'flagged=' + str(r.flagged) if ok else 'ERROR ' + r.message[:80]}")
        if ok:
            store.record_tool_call(config.run_id, store.next_seq(config.run_id),
                                   "EXECUTE", r.rule, {}, "ok",
                                   result={"flagged": r.flagged})
    cross_reference_flags(con)
    sel = select_universe(con, config)
    print(f"UNIVERSE selected={sel.selected} of {sel.total_flagged} "
          f"(fallback={sel.fallback_used})")
    for x in sel.excluded_currencies:
        print(f"         excluded {x.currency}: {x.entries} entries, "
              f"share {x.volume_share:.1%}, largest {x.largest_entry_abs:,.2f}")

    print("\n── real-model TRIAGE (Gemini) ──────────────────────────")
    provider = OpenAICompatibleProvider(
        base_url=args.base_url, model=args.model, api_key=key)
    report = run_triage(con, config, provider, sel, store, config.run_id)

    concerns = {}
    actions = {}
    for a in report.assessments:
        concerns[a.rationale_concern] = concerns.get(a.rationale_concern, 0) + 1
        actions[a.recommended_action] = actions.get(a.recommended_action, 0) + 1

    print(f"universe_covered : {report.universe_covered}/{sel.selected}")
    print(f"packs            : {len(report.pack_ids)} ({', '.join(report.pack_ids)})")
    print(f"rubric           : v{report.rubric_version}")
    print(f"concern levels   : {json.dumps(concerns)}")
    print(f"actions          : {json.dumps(actions)}")
    print(f"consistency warn : {report.consistency_warnings or 'none'}")
    print("\n── per-entry verdicts ─────────────────────────────────")
    for a in sorted(report.assessments, key=lambda x: -x.priority):
        note = a.concern_note.replace(chr(10), " ")[:110]
        print(f"{a.entry_ref:<12} {a.rationale_concern:<7} {a.recommended_action:<11} "
              f"P{a.priority} | {note}")
    print(f"\nsummary: {report.summary[:500]}")

    n_turns = store.con.execute(
        "SELECT count(*) FROM llm_outputs WHERE run_id = ?", [config.run_id]).fetchone()[0]
    print(f"\nllm_outputs rows recorded: {n_turns}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
