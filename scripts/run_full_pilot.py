"""FULL PILOT: deterministic stages -> Gemini TRIAGE -> review decisions ->
Gemini NARRATE -> finalize gates -> workpaper.xlsx. One command, real model.

Usage:
  GEMINI_API_KEY=... uv run python scripts/run_full_pilot.py \
      [--model gemini-3.5-flash-lite] [--max-universe 10]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb  # noqa: E402
import yaml  # noqa: E402

from je_agent.config import EngagementConfig  # noqa: E402
from je_agent.crossref import cross_reference_flags  # noqa: E402
from je_agent.document import build_facts_block, build_workpaper, finalize_gates  # noqa: E402
from je_agent.ingest import ingest_extract  # noqa: E402
from je_agent.llm.provider import OpenAICompatibleProvider  # noqa: E402
from je_agent.narrate import run_narrate  # noqa: E402
from je_agent.review import DecisionInput, submit_decisions  # noqa: E402
from je_agent.run_context import RunContext  # noqa: E402
from je_agent.rules import execute_rules  # noqa: E402
from je_agent.schemas import Narrative  # noqa: E402
from je_agent.store import RunStore  # noqa: E402
from je_agent.triage import run_triage  # noqa: E402
from je_agent.universe import select_universe  # noqa: E402
from je_agent.workpaper import write_workpaper  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sap_smoke_config.yaml")
    ap.add_argument("--extract", default="sap_pilot_extract.csv")
    ap.add_argument("--runs-dir", default="runs_pilot")
    ap.add_argument("--base-url", default="https://generativelanguage.googleapis.com/v1beta/openai")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--api-key-env", default="GEMINI_API_KEY")
    ap.add_argument("--reviewer", default="jdoe")
    ap.add_argument("--stop-after-triage", action="store_true",
                    help="Pause after TRIAGE: print the review queue and exit for manual review.")
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env)
    if not key:
        print(f"ERROR: set {args.api_key_env}", file=sys.stderr)
        return 2

    raw = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    config = EngagementConfig.model_validate(raw)
    provider = OpenAICompatibleProvider(base_url=args.base_url,
                                        model=args.model, api_key=key)

    ctx = RunContext.create(Path(args.runs_dir), config.run_id,
                            Path(args.config).read_text(encoding="utf-8"),
                            Path(args.extract))
    store = RunStore(ctx.runstore_path)
    store.record_run(config.run_id, "pilot", "0.1.0",
                     config.model_dump(mode="json"), model_id=provider.model_id)

    def phase(name):
        store.record_event(config.run_id, "phase_start", name)
        print(f"── {name} ──────────────────────────────")

    # 1-4 deterministic
    phase("INGEST")
    rep = ingest_extract(ctx, config)
    print(f"canonical={rep.canonical_rows} rejects={rep.rejected_rows}")
    con = duckdb.connect(str(ctx.duckdb_path))
    results = execute_rules(con, config)
    for r in results:
        if type(r).__name__ == "RuleResult":
            print(f"  {r.rule:<26} flagged={r.flagged}")
            store.record_tool_call(config.run_id, store.next_seq(config.run_id),
                                   "EXECUTE", r.rule, {}, "ok",
                                   result={"flagged": r.flagged})
    phase("CROSS_REF")
    cross_reference_flags(con)

    # 5 TRIAGE (real model)
    phase("TRIAGE (real model)")
    universe = select_universe(con, config)
    print(f"universe={universe.selected}/{universe.total_flagged}")
    triage = run_triage(con, config, provider, universe, store, config.run_id,
                        save_to=ctx.llm_dir / "triage_report.json")
    print(f"covered={triage.universe_covered} assessments={len(triage.assessments)}")

    if args.stop_after_triage:
        # enrich each entry with its actual lines so the human reviewer can judge substance
        print("\n── REVIEW QUEUE (for manual review) ──────")
        for a in sorted(triage.assessments,
                        key=lambda x: (-x.priority, x.entry_ref)):
            lines = con.execute("""
                SELECT line_no, posting_date, account, username, amount, currency,
                       description, source_doc
                FROM journal_lines WHERE entry_ref = ? ORDER BY line_no
            """, [a.entry_ref]).fetchall()
            print(f"\n■ {a.entry_ref}  | triage: {a.rationale_concern} / {a.recommended_action} "
                  f"/ P{a.priority}")
            print(f"  note: {a.concern_note[:160]}")
            for ln in lines:
                print(f"    L{ln[0]} {ln[1]} acct={ln[2]} user={ln[3]} amt={ln[4]:>14,.2f} "
                      f"{ln[5] or ''} | {(ln[6] or '')[:60]} | doc={ln[7]}")
        print("\nRun stopped for manual review. Record decisions with:")
        print(f"  uv run python scripts/record_review.py <run_dir> --reviewer <name>")
        store.close(); con.close()
        return 0

    # 6 REVIEW — policy: accept low/medium, inspect high & medium+priority>=4
    phase("REVIEW (policy decisions)")
    decisions = []
    for a in triage.assessments:
        if a.rationale_concern == "high" or a.priority >= 4:
            d = DecisionInput(entry_ref=a.entry_ref, decision="inspect",
                              reason=f"triage P{a.priority} {a.rationale_concern}: "
                                     f"{a.concern_note[:80]}")
        else:
            d = DecisionInput(entry_ref=a.entry_ref, decision="accept",
                              reason=f"triage {a.rationale_concern}: {a.concern_note[:80]}")
        decisions.append(d)
    n = submit_decisions(store, config.run_id, args.reviewer, "declared", decisions)
    print(f"{n} hash-chained decisions recorded")

    # 7 DOCUMENT — narrate (real model) then gates then workpaper
    phase("NARRATE (real model)")
    nar_res = run_narrate(con, config, provider, universe, store, config.run_id,
                          triage_summary=triage.summary,
                          save_to=ctx.llm_dir / "narrative.json")
    narrative: Narrative = nar_res.artifact
    print(f"narrative sections={[s['heading'] for s in narrative.sections]}")

    phase("FINALIZE GATES")
    facts = build_facts_block(con, config, universe, triage, store)
    gates = finalize_gates(con, config, universe, narrative, facts, store,
                           accepted_limitations=set(), procedure_failures={})
    for name, ok in [("1 review completeness", gates.gate1_review_complete),
                     ("2 procedure completeness", gates.gate2_procedures_complete),
                     ("3 narrative citations", gates.gate3_citations_valid),
                     ("4 limitation acceptance", gates.gate4_limitations_accepted)]:
        print(f"  gate {name:<28} {'PASS' if ok else 'FAIL'}")
    if not gates.all_passed:
        for p in gates.problems:
            print(f"  • {p}")

    wp = build_workpaper(ctx, config, facts, narrative, store,
                         limitations_accepted=set(active_limitations(con, config, universe)))
    out = write_workpaper(ctx.artifacts_dir / "workpaper.xlsx", wp)
    store.set_status(config.run_id, "finalized", "DOCUMENT")
    store.record_event(config.run_id, "finalize", f"workpaper written: {out.name}")
    print(f"\n✔ FINALIZED — workpaper: {out}")
    store.close()
    con.close()
    return 0


def active_limitations(con, config, universe):
    from je_agent.document import active_limitations as _al

    return _al(con, config, universe)


if __name__ == "__main__":
    raise SystemExit(main())
