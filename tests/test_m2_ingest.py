"""M2 tests: ingestion, canonical mapping, rejects, DQ profile incl. v1.6 Z1."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import duckdb
import pytest
import yaml

from je_agent.config import load_config
from je_agent.ingest import IngestReport, ingest_extract
from je_agent.run_context import RunContext


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_run(tmp_path: Path, extract: Path, config_overrides: dict | None = None):
    from tests.conftest import base_config_dict, write_config

    cfg = base_config_dict(**(config_overrides or {}))
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    ctx = RunContext.create(
        tmp_path / "runs", config.run_id,
        (tmp_path / "config.yaml").read_text(encoding="utf-8"),
        extract,
    )
    return ctx, config


def write_extract(tmp_path: Path, rows: list[str], header: str =
                  "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE") -> Path:
    p = tmp_path / f"extract_{abs(hash(tuple(rows)))}.csv"
    p.write_text("\n".join([header] + rows), encoding="utf-8")
    return p


def table_rows(ctx, sql: str) -> list[tuple]:
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_ingest_happy_path_reconciles(tmp_path, clean_extract):
    ctx, config = make_run(tmp_path, clean_extract)
    report = ingest_extract(ctx, config)

    assert isinstance(report, IngestReport)
    assert report.raw_rows == 10
    assert report.canonical_rows == 10
    assert report.rejected_rows == 0
    assert report.observed_min_posting_date == "2026-03-18"
    assert report.observed_max_posting_date == "2026-07-12"
    assert report.currencies == {"USD": 10}

    rows = table_rows(ctx, """
        SELECT entry_ref, line_no, username, is_manual, entry_type_source, amount
        FROM journal_lines ORDER BY entry_ref, line_no
    """)
    # no entry_type mapped in base config => tier-2 DERIVED heuristic decides:
    # JE001/JE003/JE005 system users; JE002/JE004 human users
    by_ref = {r[0]: r for r in rows}
    assert by_ref["JE001"][3] is False and by_ref["JE001"][4] == "derived"
    assert by_ref["JE002"][3] is True and by_ref["JE002"][4] == "derived"

    # signed debit-positive preserved, both JE002 lines present and balancing
    je002 = table_rows(ctx, """
        SELECT line_no, amount FROM journal_lines
        WHERE entry_ref = 'JE002' ORDER BY line_no
    """)
    assert [float(r[1]) for r in je002] == [-230.50, 230.50]

    # whole clean population balances to zero
    total = table_rows(ctx, "SELECT sum(amount) FROM journal_lines")[0][0]
    assert abs(float(total)) < 0.01


def test_clean_population_raises_no_warnings(tmp_path, clean_extract):
    ctx, config = make_run(tmp_path, clean_extract)
    report = ingest_extract(ctx, config)
    ids = [w.warning_id for w in report.dq_warnings]
    assert not [i for i in ids if i != "dq_missing_fields"], f"unexpected warnings: {report.summary()}"


# ---------------------------------------------------------------------------
# rejects + reconciliation
# ---------------------------------------------------------------------------


def test_bad_row_lands_in_rejects_with_reason(tmp_path):
    rows = [
        "JE100,1,2026-05-01,4000,SAPUSER,ok sale,DOC900,100.00,USD,system",
        "JE101,1,NOT-A-DATE,4000,SAPUSER,bad date row,DOC901,50.00,USD,system",       # bad date
        "JE102,1,2026-05-02,4000,SAPUSER,missing amount,DOC902,,USD,system",          # empty amount
        ",1,2026-05-03,4000,SAPUSER,missing ref,DOC903,10.00,USD,system",             # missing ref
        "JE103,,2026-05-04,4000,SAPUSER,no line no ok,DOC904,20.00,USD,system",       # line synthesized
    ]
    extract = write_extract(tmp_path, rows)
    ctx, config = make_run(tmp_path, extract)
    report = ingest_extract(ctx, config)

    assert report.raw_rows == 5
    assert report.rejected_rows == 3
    assert report.canonical_rows == 2

    rejects = table_rows(ctx, "SELECT staging_row, reason FROM ingest_rejects ORDER BY staging_row")
    reasons = " | ".join(r[1] for r in rejects).lower()
    assert "date" in reasons
    assert "amount" in reasons
    assert "ref" in reasons or "source_doc" in reasons

    # reconciliation: raw = canonical + rejects
    assert report.canonical_rows + report.rejected_rows == report.raw_rows


# ---------------------------------------------------------------------------
# is_manual derivation (v1.6 Z3)
# ---------------------------------------------------------------------------


def test_derived_tier_system_patterns_and_blank_user(tmp_path):
    rows = [
        # USER matches SAP* prefix => derived system
        "JE200,1,2026-05-01,4000,SAPUSER,auto posting,DOC950,100.00,USD,",
        # WF-BATCH exact => system
        "JE201,1,2026-05-01,5000,WF-BATCH,payroll run,DOC951,200.00,USD,",
        # boundary case: ASAPUSER must NOT match SAP*
        "JE202,1,2026-05-02,6000,ASAPUSER,human posting,DOC952,300.00,USD,",
        # blank user => NOT manual (conservative) + counted in missing fields
        "JE203,1,2026-05-02,7000,,unattributed posting,DOC953,400.00,USD,",
        # suffix pattern *_RFC (must END with _RFC)
        "JE204,1,2026-05-03,8000,BOT_PAY_RFC,interface posting,DOC954,500.00,USD,",
    ]
    extract = write_extract(tmp_path, rows)   # ENTRY_TYPE column present but blank
    overrides = {"source": {
        "system": "generic", "amount_column": "AMOUNT",
        "column_map": {
            "posting_date": "POST_DATE", "account": "ACCOUNT", "username": "USER",
            "description": "DESCR", "source_doc": "DOC", "entry_ref": "ENTRY", "entry_type": "ENTRY_TYPE",
        }}}
    ctx, config = make_run(tmp_path, extract, overrides)

    report = ingest_extract(ctx, config)
    assert report.canonical_rows == 5

    got = {r[0]: (r[1], r[2]) for r in table_rows(ctx, """
        SELECT entry_ref, is_manual, entry_type_source FROM journal_lines
    """)}
    assert got["JE200"] == (False, "derived")   # SAP* matched
    assert got["JE201"] == (False, "derived")   # exact match
    assert got["JE202"] == (True,  "derived")   # boundary: ASAPUSER human
    assert got["JE203"] == (False, "derived")   # blank user conservative FALSE
    assert got["JE204"] == (False, "derived")   # *_RFC suffix matched


# ---------------------------------------------------------------------------
# Z1 coverage warnings
# ---------------------------------------------------------------------------


def test_z1_shortfall_critical_when_extract_ends_before_declared(tmp_path):
    rows = [
        "JE300,1,2026-06-28,4000,SAPUSER,sale,DOC970,100.00,USD,system",
        "JE300,2,2026-06-28,1200,SAPUSER,sale,DOC970,-100.00,USD,system",
    ]
    extract = write_extract(tmp_path, rows)
    overrides = {"source": {
        "system": "generic", "amount_column": "AMOUNT",
        "extract_through_date": "2026-07-15",
        "column_map": {
            "posting_date": "POST_DATE", "account": "ACCOUNT", "username": "USER",
            "description": "DESCR", "source_doc": "DOC", "entry_ref": "ENTRY", "entry_type": "ENTRY_TYPE",
        }}}
    ctx, config = make_run(tmp_path, extract, overrides)
    report = ingest_extract(ctx, config)

    ids = {w.warning_id: w for w in report.dq_warnings}
    assert "dq_extract_shortfall_declared" in ids
    shortfall = ids["dq_extract_shortfall_declared"]
    assert shortfall.severity == "critical" and shortfall.non_dismissible

    # also triggers post-close coverage warning (period_end 06-30 + 10 days = 07-10 > 06-28)
    assert "dq_no_post_close_coverage" in ids
    cov = ids["dq_no_post_close_coverage"]
    assert cov.severity == "warning"


def test_z1_full_coverage_no_warning(tmp_path):
    rows = [
        "JE310,1,2026-06-15,4000,SAPUSER,sale,DOC971,100.00,USD,system",
        "JE310,2,2026-06-15,1200,SAPUSER,sale,DOC971,-100.00,USD,system",
        "JE311,1,2026-07-15,4000,SAPUSER,reversal window covered,DOC972,-100.00,USD,system",
        "JE311,2,2026-07-15,1200,SAPUSER,reversal window covered,DOC972,100.00,USD,system",
    ]
    extract = write_extract(tmp_path, rows)
    overrides = {"source": {
        "system": "generic", "amount_column": "AMOUNT",
        "extract_through_date": "2026-07-15",
        "column_map": {
            "posting_date": "POST_DATE", "account": "ACCOUNT", "username": "USER",
            "description": "DESCR", "source_doc": "DOC", "entry_ref": "ENTRY", "entry_type": "ENTRY_TYPE",
        }}}
    ctx, config = make_run(tmp_path, extract, overrides)
    report = ingest_extract(ctx, config)

    ids = [w.warning_id for w in report.dq_warnings]
    assert "dq_extract_shortfall_declared" not in ids
    assert "dq_no_post_close_coverage" not in ids
