"""Stress-test runner — generates labeled populations (incl. 100k+ lines),
runs the full JE Agent pipeline on each, then scores precision/recall/F1
per rule against the injected anomaly labels. Results are logged to
stress_output/results.json AND stress_output/notes.md for the final report.

Usage:
    uv run python -u scripts/stress_test.py [--scenarios small,medium,large,huge] [--model gemini-3.5-flash-lite]

Scenarios:
    small  : 1k base docs (~2k lines) + ~30 anomalies each
    medium : 10k base docs (~20k lines) + ~60 anomalies each
    large  : 50k base docs (~100k lines) + ~100 anomalies each
    huge   : 100k base docs (~200k lines) + ~150 anomalies each

Deterministic: same seed -> same population. The LLM triage leg is optional
(--skip-triage to measure deterministic rules only).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from je_agent.config import load_config  # noqa: E402
from je_agent.ingest import ingest_extract  # noqa: E402
from je_agent.rules import execute_rules  # noqa: E402
from je_agent.crossref import cross_reference_flags  # noqa: E402
from je_agent.universe import select_universe  # noqa: E402
from je_agent.run_context import RunContext  # noqa: E402
from je_agent.store import RunStore  # noqa: E402

from stress_gen import Scenario, build_scenario, write_csv  # noqa: E402

OUT = ROOT / "stress_output"
ANOMALY_RULES = ["round_amounts", "entry_splitting", "period_end", "unusual_pairs",
                 "unusual_users", "balance_check", "reversals",
                 "date_divergence", "high_risk_system_pairs"]

SCENARIOS = {
    "small":  {"n_docs": 1_000,  "seed": 1101,  "anom": {"round_amounts": 6, "entry_splitting": 5,
               "period_end": 4, "unusual_pairs": 5, "unusual_users": 4, "balance_check": 3,
               "reversals": 3, "date_divergence": 4, "high_risk_system_pairs": 3}},
    "medium": {"n_docs": 10_000, "seed": 2202,  "anom": {"round_amounts": 12, "entry_splitting": 10,
               "period_end": 8, "unusual_pairs": 10, "unusual_users": 8, "balance_check": 6,
               "reversals": 6, "date_divergence": 8, "high_risk_system_pairs": 6}},
    "large":  {"n_docs": 50_000, "seed": 3303,  "anom": {"round_amounts": 20, "entry_splitting": 16,
               "period_end": 12, "unusual_pairs": 18, "unusual_users": 12, "balance_check": 10,
               "reversals": 12, "date_divergence": 16, "high_risk_system_pairs": 10}},
    "huge":   {"n_docs": 100_000, "seed": 4404, "anom": {"round_amounts": 30, "entry_splitting": 24,
               "period_end": 18, "unusual_pairs": 26, "unusual_users": 18, "balance_check": 15,
               "reversals": 20, "date_divergence": 30, "high_risk_system_pairs": 18}},
}


def config_yaml_for(scenario: str, run_id: str) -> str:
    return f"""run_id: {run_id}
period_end: '2024-12-31'
materiality: {{overall: 500000, performance: 175000, currency: USD}}
source:
  system: generic
  amount_column: AMOUNT
  currency_column: CUR
  column_map:
    posting_date: DATE
    document_date: DOCDAT
    account: ACCT
    username: USER
    description: DESC
    source_doc: REF
    entry_ref: REF
    entry_created_date: DATE
    entry_type: TYPE
review:
  max_universe_size: 2000
  overflow_policy: stratify
  pack_size: 20
risk_context:
  high_risk_users: [SAP_JOB]
llm_privacy: {{mode: zero_retention, pii_scrubbing: true}}
report_lang: {{lang: en}}
provider:
  base_url: {os.environ.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai')}
  model: {os.environ.get('PILOT_MODEL', 'gemini-3.5-flash-lite')}
reviewer: {{name: stress-test}}
"""


def _anomaly_amount(scenario: Scenario, ref: str) -> float | None:
    """Max |amount| of an injected doc ref (from the generated CSV lines)."""
    best = None
    for line in scenario.lines[1:]:
        parts = line.split(",")
        if parts[0] == ref:
            try:
                amt = abs(float(parts[8]))
                best = amt if best is None else max(best, amt)
            except (ValueError, IndexError):
                pass
    return best


def run_deterministic(scenario: Scenario, out_dir: Path) -> dict:
    """Ingest -> rules -> cross-ref; return flagged counts + universe per rule."""
    import shutil

    run_id = f"STRESS_{scenario.name.upper()}"
    config = load_config(out_dir / "config.yaml")
    stale = out_dir / run_id
    if stale.exists():
        shutil.rmtree(stale)          # cleanup of a previous run of THIS scenario
    ctx = RunContext.create(out_dir, run_id, (out_dir / "config.yaml").read_text("utf-8"),
                            out_dir / "extract.csv")
    store = RunStore(ctx.runstore_path)
    store.record_run(run_id, "stress", "1.0.0", config.model_dump(mode="json"),
                     model_id="deterministic")
    rep = ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    results = execute_rules(con, config)
    cross_reference_flags(con)
    sel = select_universe(con, config)
    con.close()
    store.close()

    rule_counts = {}
    for r in results:
        if type(r).__name__ == "RuleResult":
            rule_counts[r.rule] = r.flagged

    return {"canonical_rows": rep.canonical_rows, "rejected": rep.rejected_rows,
            "rule_counts": rule_counts, "universe_selected": sel.selected,
            "universe_total_flagged": sel.total_flagged,
            "universe_refs": [e["entry_ref"] for e in sel.entries],
            "workspace": str(ctx.duckdb_path)}


def score(scenario: Scenario, det: dict, run_dir: Path, config) -> dict:
    """Compare flagged (per rule) vs injected anomalies: precision/recall/F1."""
    con = duckdb.connect(str(det["workspace"]), read_only=True)
    flagged = {}
    for rule in ANOMALY_RULES:
        rows = con.execute(f"SELECT entry_ref FROM flags_{rule}").fetchall()
        flagged[rule] = {r[0] for r in rows}
    con.close()

    injection_map = {ref: rule for ref, rule, _ in scenario.anomalies}
    per_rule = {}
    for rule in ANOMALY_RULES:
        # expected refs: every anomaly labeled with this rule, incl. split parts
        injected_in_rule = {ref for ref, r in injection_map.items() if r == rule}
        flagged_in_rule = flagged.get(rule, set())
        tp = len(injected_in_rule & flagged_in_rule)
        fn = len(injected_in_rule - flagged_in_rule)
        # FP only counts flags on CLEAN base docs (not injections of other rules)
        clean = {r.split(",")[0] for r in scenario.lines[1:] if r.split(",")[0].startswith("B")}
        fp_clean = len(flagged_in_rule & clean)
        precision = tp / (tp + fp_clean) if (tp + fp_clean) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 1.0
        per_rule[rule] = {"injected": len(injected_in_rule), "flagged": len(flagged_in_rule),
                          "tp": tp, "fn": fn, "fp_clean": fp_clean,
                          "precision": round(precision, 4), "recall": round(recall, 4),
                          "f1": round(f1, 4)}

    all_injected = {ref for ref, _, _ in scenario.anomalies}
    all_flagged = set()
    for s in flagged.values():
        all_flagged |= s
    tp_all = len(all_injected & all_flagged)
    fn_all = len(all_injected - all_flagged)
    fp_all = len(all_flagged - all_injected)
    # aggregate
    precision = tp_all / (tp_all + fp_all) if (tp_all + fp_all) else 1.0
    recall = tp_all / (tp_all + fn_all) if (tp_all + fn_all) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 1.0

    # ---- what the REVIEWER actually sees (the universe) --------------------
    # Design: universe = flagged entries above performance materiality (PM).
    # Sub-PM anomalies are out of scope BY DESIGN — so the meaningful universe
    # recall is measured only over injections whose amount >= PM.
    pm = config.materiality.performance
    injected_in_univ = 0
    universe_eligible = 0
    univ = set(det["universe_refs"])
    for ref in all_injected:
        amt = _anomaly_amount(scenario, ref)
        if amt is None or amt < pm:
            continue
        universe_eligible += 1
        if ref in univ:
            injected_in_univ += 1
    univ_recall = injected_in_univ / universe_eligible if universe_eligible else 1.0

    return {"per_rule": per_rule,
            "aggregate": {"injected": len(all_injected), "flagged": len(all_flagged),
                          "tp": tp_all, "fn": fn_all, "fp": fp_all,
                          "precision": round(precision, 4), "recall": round(recall, 4),
                          "f1": round(f1, 4)},
            "universe": {"selected": len(univ),
                         "above_pm_injected": universe_eligible,
                         "injected_in_universe": injected_in_univ,
                         "universe_recall": round(univ_recall, 4)}}


def run_triage_leg(name: str, run_dir: Path) -> dict:
    """Run real LLM triage on the scenario's universe; score agreement with
    injected ground truth. Uses OpenAICOMpatibleProvider (Gemini via env key).
    Unused-injected = out-of-scope sub-PM entries are excluded (by design)."""
    import json as _json

    from je_agent.llm.provider import OpenAICompatibleProvider
    from je_agent.run_context import RunContext
    from je_agent.store import RunStore
    from je_agent.triage import run_triage
    from je_agent.universe import select_universe

    config = load_config(run_dir / "config.yaml")
    # matches run_deterministic: f"STRESS_{scenario.name.upper()}" where
    # scenario.name = f"stress-{name}" → "STRESS_STRESS-SMALL"
    run_id = f"STRESS_STRESS-{name.upper()}"
    ctx = RunContext(run_dir / run_id)
    store = RunStore(ctx.runstore_path)

    con = duckdb.connect(str(ctx.duckdb_path))
    universe = select_universe(con, config)
    # re-derive ground truth from the extract present in this run dir
    sc = build_scenario(f"stress-{name}",
                        SCENARIOS[name]["n_docs"], SCENARIOS[name]["seed"],
                        SCENARIOS[name]["anom"])

    key = os.environ.get("JEAGENT_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    provider = OpenAICompatibleProvider(base_url=config.provider.base_url,
                                        model=config.provider.model, api_key=key)
    report = run_triage(con, config, provider, universe, store, run_id,
                        save_to=run_dir / "triage_report.json")
    con.close()
    store.close()

    # ---- score agreement ---------------------------------------------------
    anomaly_by_ref = {ref: rule for ref, rule, _ in sc.anomalies}
    adj = {a.entry_ref: a for a in report.assessments}

    n_inj_inp = n_inj_insp = n_clean_inp = n_clean_accept = 0
    false_neg = []   # injected anomaly the LLM said "accept" (missed)
    false_pos = []   # clean entry the LLM said "inspect" (false alarm)
    for ref, a in adj.items():
        if ref in anomaly_by_ref:
            n_inj_inp += 1
            if a.recommended_action == "inspect":
                n_inj_insp += 1
            else:
                false_neg.append((ref, a.recommended_action, a.concern_note[:90]))
        else:
            n_clean_inp += 1
            if a.recommended_action == "accept_flag":
                n_clean_accept += 1
            else:
                false_pos.append((ref, a.recommended_action, a.concern_note[:90]))

    inj_recall = n_inj_insp / n_inj_inp if n_inj_inp else 1.0
    # precision of 'inspect' calls against ground truth:
    n_inspected = sum(1 for a in adj.values() if a.recommended_action == "inspect")
    insp_precision = n_inj_insp / n_inspected if n_inspected else 1.0

    print(f"  TRIAGE leg: {len(adj)} assessed | injected {n_inj_insp}/{n_inj_inp} "
          f"flagged inspect (recall {inj_recall:.2%}) | inspect-precision "
          f"{insp_precision:.2%} | clean entries wrongly inspect: {len(false_pos)}")
    for ref, act, note in false_neg[:5]:
        print(f"    MISSED injected {ref}: LLM said '{act}' — {note}")
    for ref, act, note in false_pos[:5]:
        print(f"    FALSE ALARM clean {ref}: LLM said '{act}' — {note}")

    return {"assessed": len(adj), "injected_assessed": n_inj_inp,
            "injected_inspect": n_inj_insp, "injected_recall": round(inj_recall, 4),
            "inspect_precision": round(insp_precision, 4),
            "clean_assessed": n_clean_inp, "clean_accept": n_clean_accept,
            "false_neg": [f"{r} ({a})" for r, a, _ in false_neg],
            "false_pos": [f"{r} ({a})" for r, a, _ in false_pos]}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="small,medium,large,huge")
    ap.add_argument("--triage", action="store_true",
                    help="run the real LLM triage leg on `small` and score human-agreement")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    all_results = {}
    start_all = time.time()

    for name in [s.strip() for s in args.scenarios.split(",") if s.strip()]:
        spec = SCENARIOS[name]
        sc = build_scenario(f"stress-{name}", spec["n_docs"], spec["seed"], spec["anom"])
        run_dir = OUT / f"run-{name}"
        run_dir.mkdir(exist_ok=True)
        extract_path = run_dir / "extract.csv"
        write_csv(sc, extract_path)
        (run_dir / "config.yaml").write_text(config_yaml_for(name, f"STRESS_{name.upper()}"),
                                             encoding="utf-8")
        n_lines = len(sc.lines) - 1
        print(f"\n=== {name}: {n_lines:,} lines ({sc.n_base_docs:,} base docs, "
              f"{len(sc.anomalies)} injections) ===")

        config = load_config(run_dir / "config.yaml")

        t0 = time.time()
        det = run_deterministic(sc, run_dir)
        print(f"  ingest {det['canonical_rows']:,} rows ({det['rejected']} rejected) — "
              f"{time.time() - t0:.1f}s")
        print("  rule flags: " + ", ".join(f"{k}={v}" for k, v in det["rule_counts"].items()))

        t0 = time.time()
        s = score(sc, det, run_dir, config)
        print(f"  scored in {time.time() - t0:.1f}s — aggregate "
              f"precision={s['aggregate']['precision']} recall={s['aggregate']['recall']} "
              f"f1={s['aggregate']['f1']} | universe_recall={s['universe']['universe_recall']} "
              f"({s['universe']['injected_in_universe']}/{s['aggregate']['injected']} injected make the universe)")

        per_rule_lines = []
        for rule, m in s["per_rule"].items():
            flag = "✓" if m["recall"] >= 0.85 else "~" if m["recall"] >= 0.5 else "✗"
            print(f"    {flag} {rule:<18} recall={m['recall']:.2%} precision={m['precision']:.2%} "
                  f"f1={m['f1']:.2%} ({m['tp']}/{m['injected']} injected, {m['fp_clean']} fp on clean)")
            per_rule_lines.append(f"- {rule}: recall {m['recall']:.2%}, precision "
                                  f"{m['precision']:.2%}, F1 {m['f1']:.2%} "
                                  f"({m['tp']}/{m['injected']} caught, {m['fp_clean']} false positives)")

        all_results[name] = {"lines": n_lines, "base_docs": sc.n_base_docs,
                             "injections": len(sc.anomalies), "det": det, "score": s}
        (run_dir / "result.json").write_text(json.dumps(all_results[name], indent=1),
                                             encoding="utf-8")

    total = time.time() - start_all
    (OUT / "results.json").write_text(json.dumps(all_results, indent=1), encoding="utf-8")

    triage_result = None
    if args.triage:
        print("\n=== LLM triage leg (small scenario, real provider) ===")
        print("  running… (LLM calls; takes a few minutes)")
        triage_result = run_triage_leg("small", OUT / "run-small")
        all_results["small"]["triage_agreement"] = triage_result
        (OUT / "results.json").write_text(json.dumps(all_results, indent=1),
                                          encoding="utf-8")

    # ---- notes.md for the report ------------------------------------------
    note_lines = [
        "# JE Agent — Stress-Test Results (labeled anomalies)",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} · total run time {total:.1f}s · "
        "deterministic rules (LLM triage leg separate).",
        "",
        "## Methodology (v2)",
        "",
        "Synthetic journal populations with **known injected anomalies**, one labeled "
        "document per case, covering all 10 rules. Base populations are **realistic, not "
        "sterile**: ~90% manual + ~10% system-posted entries (IDOC_AUTO / WF-BATCH / "
        "SAP_JOB), legit-rare users (~5%), legitimately large invoices, month-start "
        "postings — so false positives CAN occur and are measured.",
        "",
        "**Scoring** — for each rule: `tp` = injected anomalies flagged, `fn` = injected "
        "missed, `fp` = flags on clean base docs (the noise). Recall = tp/(tp+fn); "
        "precision = tp/(tp+fp); F1 = harmonic mean. Out-of-scope injections (below "
        "performance materiality, excluded by design) are excluded from universe recall.",
        "",
        "**Rules injected:** round_amounts, entry_splitting, period_end, unusual_pairs, "
        "unusual_users, balance_check, reversals, date_divergence, high_risk_system_pairs, "
        "manual_entries (implicit — everything is a journal entry).",
        "",
        "## Aggregate",
        "",
        "| Scenario | Lines | Injections | Recall | Precision | F1 | Universe recall (PM-scoped) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in all_results.items():
        u = r["score"]["universe"]
        note_lines.append(f"| {name} | {r['lines']:,} | {r['injections']} | "
                          f"{r['score']['aggregate']['recall']:.2%} | "
                          f"{r['score']['aggregate']['precision']:.2%} | "
                          f"{r['score']['aggregate']['f1']:.2%} | "
                          f"{u['universe_recall']:.2%} "
                          f"({u['injected_in_universe']}/{u['above_pm_injected']} above-PM) |")
    for name, r in all_results.items():
        note_lines.append(f"## {name} ({r['lines']:,} lines)")
        for rule, m in r["score"]["per_rule"].items():
            note_lines.append(f"- {rule}: recall {m['recall']:.2%}, precision "
                              f"{m['precision']:.2%}, F1 {m['f1']:.2%} "
                              f"({m['tp']}/{m['injected']} caught, {m['fp_clean']} false positives)")
        u = r["score"]["universe"]
        note_lines.append(f"- universe: {u['selected']} selected of "
                          f"{len(r['det'].get('universe_refs', []))} refs; "
                          f"{u['injected_in_universe']}/{u['above_pm_injected']} above-PM "
                          f"injected anomalies in universe (recall {u['universe_recall']:.2%})")
        note_lines.append("")
    (OUT / "notes.md").write_text("\n".join(note_lines), encoding="utf-8")

    print(f"\n💾 results: {OUT / 'results.json'}\n💾 notes: {OUT / 'notes.md'}")
    return 0


def _rule_lines(r: dict) -> list[str]:
    out = []
    for rule, m in r["score"]["per_rule"].items():
        out.append(f"- {rule}: recall {m['recall']:.2%}, precision {m['precision']:.2%}, "
                   f"F1 {m['f1']:.2%} ({m['tp']}/{m['injected']} caught, "
                   f"{m['fp_clean']} false positives)")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
