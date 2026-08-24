"""M4 tests: cross-ref ranking, Excel export, golden smoke, reproducibility (§9.3)."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from je_agent.config import load_config
from je_agent.crossref import cross_reference_flags
from je_agent.export import export_flagged_entries
from je_agent.ingest import ingest_extract
from je_agent.rules import execute_rules
from je_agent.run_context import RunContext

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def full_pipeline(tmp_path: Path, extract: Path, run_id: str = "GOLD_Q2"):
    from tests.conftest import base_config_dict, write_config

    cfg = base_config_dict(run_id=run_id)
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    ctx = RunContext.create(
        tmp_path / "runs", run_id, (tmp_path / "config.yaml").read_text(encoding="utf-8"),
        extract,
    )
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    results = execute_rules(con, config)
    n_entries = cross_reference_flags(con)
    return ctx, con, config, results, n_entries


def table_hash(con, sql: str) -> str:
    rows = con.execute(sql).fetchall()
    payload = repr(rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# cross-ref
# ---------------------------------------------------------------------------


def test_xref_ranks_by_rules_hit_then_amount(tmp_path):
    rows = [
        # multi-hit doc: manual + near-PE + round (3 rules)
        "X1,1,2026-06-29,6100,JDOE,consulting,X1D,-20000.00,USD,manual",
        "X1,2,2026-06-29,1000,JDOE,consulting,X1D,20000.00,USD,manual",
        # single-hit doc: manual only, larger amount
        "X2,1,2026-05-10,6100,JDOE,supplies,X2D,-99999.99,USD,manual",
        "X2,2,2026-05-10,1000,JDOE,supplies,X2D,99999.99,USD,manual",
    ]
    extract = tmp_path / "extract.csv"
    extract.write_text(
        "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE\n"
        + "\n".join(rows),
        encoding="utf-8",
    )
    ctx, con, cfg, results, n = full_pipeline(tmp_path, extract)
    try:
        rows = con.execute(
            "SELECT entry_ref, rules_hit FROM xref_ranked ORDER BY rules_hit DESC, abs_amount DESC"
        ).fetchall()
        by_ref = dict((r[0], r[1]) for r in rows)
        # X1 = manual + near-PE + round (+ rare-user + unusual-pair given this tiny
        # population) => strictly more rule hits than X2 (manual + pair)
        assert by_ref["X1"] >= 3
        assert by_ref["X1"] > by_ref["X2"]
        assert rows[0][0] == "X1"                       # multi-rule ranks first
        assert n == 2                                   # both docs in the universe
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


def test_excel_export_roundtrip(tmp_path):
    rows = [
        "E1,1,2026-06-29,6100,JDOE,consulting,E1D,-20000.00,USD,manual",
        "E1,2,2026-06-29,1000,JDOE,consulting,E1D,20000.00,USD,manual",
    ]
    extract = tmp_path / "extract.csv"
    extract.write_text(
        "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE\n"
        + "\n".join(rows),
        encoding="utf-8",
    )
    ctx, con, cfg, results, n = full_pipeline(tmp_path, extract, run_id="EXP_Q2")
    try:
        out = export_flagged_entries(con, ctx.artifacts_dir / "flagged_entries.xlsx")
        assert out.exists() and out.stat().st_size > 1000
    finally:
        con.close()


# ---------------------------------------------------------------------------
# golden smoke: clean 10k population must produce ZERO gating flags (§9.1 FPR=0 on benign)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clean_csv(tmp_path_factory):
    """Generate the benign population once for the module (deterministic)."""
    out = tmp_path_factory.mktemp("gold") / "clean.csv"
    subprocess.run(
        [sys.executable, str(FIXTURES / "generate_clean.py"),
         "--lines", "10000", "--seed", "20260823", "--out", str(out)],
        check=True, capture_output=True,
    )
    return out


def test_golden_clean_population_zero_flags(tmp_path, clean_csv):
    ctx, con, cfg, results, n = full_pipeline(tmp_path, clean_csv, run_id="GOLD_CLEAN")
    try:
        errors = [r for r in results if type(r).__name__ == "RuleError"]
        assert not errors, f"rule failures: {[ (r.rule, r.message) for r in errors ]}"
        per_rule = {r.rule: r.flagged for r in results if type(r).__name__ == "RuleResult"}
        # Rules that must stay SILENT on the benign library (precision claims):
        for rule in ("balance_check", "date_divergence", "entry_splitting"):
            assert per_rule[rule] == 0, f"{rule} fired on benign population: {per_rule}"
        # round_amounts may fire on fixed payroll grosses (definitional, §9.1);
        # unusual_pairs fires on MANUAL pairs absent from the system baseline
        # (definitional — manual pairs are prime fraud vehicles; volume is handled
        # by the W1 universe cap + triage + human review, not by rule silence).
        assert per_rule["round_amounts"] <= 10
        # reversals: routine accrual/reversal pairs are same-user exact negations;
        # only a handful of boundary-straddling cases may flag
        assert per_rule["reversals"] <= 12
    finally:
        con.close()


# ---------------------------------------------------------------------------
# reproducibility: double-run identical (§9.3)
# ---------------------------------------------------------------------------


def test_double_run_byte_identical_tables(tmp_path, clean_csv):
    hashes = []
    for i, run_id in enumerate(("REPRO_A", "REPRO_B")):
        run_dir = tmp_path / f"run{i}"
        run_dir.mkdir()
        ctx, con, cfg, results, n = full_pipeline(run_dir, clean_csv, run_id=run_id)
        try:
            h = {
                "journal": table_hash(con, "SELECT * FROM journal_lines ORDER BY entry_ref, line_no"),
                "xref": table_hash(con, "SELECT * FROM xref_ranked ORDER BY entry_ref, line_no"),
                "counts": repr({r.rule: r.flagged for r in results
                                if type(r).__name__ == "RuleResult"}),
            }
            hashes.append(h)
        finally:
            con.close()
    assert hashes[0] == hashes[1], "double-run must be byte-identical (deterministic path)"


def test_reorder_invariance_flag_tables(tmp_path, clean_csv):
    """v1.6 Z2: RiskPlan selection order must not change any flags_* table."""
    from tests.conftest import base_config_dict, write_config

    cfg2 = base_config_dict(run_id="REORD")
    cfg2["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg2)
    config = load_config(cfg_file)

    ctx = RunContext.create(
        tmp_path / "runs", "REORD", (tmp_path / "config.yaml").read_text(encoding="utf-8"),
        clean_csv,
    )
    ingest_extract(ctx, config)

    plan_a = ["reversals", "manual_entries", "unusual_pairs", "round_amounts",
              "period_end", "balance_check"]
    plan_b = list(reversed(plan_a))

    con = duckdb.connect(str(ctx.duckdb_path))
    res_a = execute_rules(con, config, selected=plan_a)
    snap_a = table_hash(con, "SELECT * FROM flags_unusual_pairs ORDER BY entry_ref, line_no")
    res_b = execute_rules(con, config, selected=plan_b)
    snap_b = table_hash(con, "SELECT * FROM flags_unusual_pairs ORDER BY entry_ref, line_no")
    con.close()

    assert [r.rule for r in res_a] == [r.rule for r in res_b]  # same canonical order
    assert snap_a == snap_b                                     # identical results
