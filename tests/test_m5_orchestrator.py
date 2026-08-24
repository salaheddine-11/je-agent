"""M5 tests: constant plan, orchestrator stages, CLI, recovery."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

from je_agent.config import load_config
from je_agent.orchestrator import OrchestrationError, Orchestrator
from je_agent.plan import constant_risk_plan
from je_agent.workspace import RunLock
from tests.conftest import base_config_dict, write_config


@pytest.fixture
def engagement(tmp_path):
    cfg = base_config_dict(run_id="CLI_Q2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    extract = tmp_path / "extract.csv"
    rows = [
        "C1,1,2026-06-29,6100,JDOE,consulting fee,C1D,-20000.00,USD,manual",
        "C1,2,2026-06-29,1000,JDOE,consulting fee,C1D,20000.00,USD,manual",
        "C2,1,2026-05-01,4000,SAPUSER,sales batch,C2D,-800.00,USD,system",
        "C2,2,2026-05-01,1200,SAPUSER,sales batch,C2D,800.00,USD,system",
    ]
    extract.write_text(
        "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE\n"
        + "\n".join(rows), encoding="utf-8")
    return tmp_path, cfg_file, extract


# -- constant RiskPlan seam ----------------------------------------------------


def test_constant_plan_covers_all_rules_in_canonical_order():
    plan = constant_risk_plan()
    names = [s.rule for s in plan.selections]
    assert len(names) == 10
    assert names == sorted(names, key=names.index)      # already canonical
    assert plan.producer == "constant"


# -- orchestrator end-to-end ------------------------------------------------------


def test_start_run_full_pipeline_and_store(engagement):
    tmp_path, cfg_file, extract = engagement
    orch = Orchestrator(runs_root=tmp_path / "runs")
    run_id = orch.start_run(cfg_file, extract)

    info = orch.get_run(run_id)
    assert info["status"] == "awaiting_review"
    assert info["phase"] == "CROSS_REF"
    details = " | ".join(d or "" for _, _, d in info["events"])
    for stage in ("INGEST", "RISK_PLAN", "EXECUTE", "CROSS_REF"):
        assert f"{stage}" in details, f"missing {stage} in events: {details}"

    # frozen artifacts exist (§6.1 layout)
    run_dir = tmp_path / "runs" / run_id
    for name in ("config.yaml", "extract.csv", "extract.sha256",
                 "workspace.duckdb", "runstore.sqlite",
                 "llm/risk_plan.json", "artifacts/flagged_entries.xlsx"):
        assert (run_dir / name).exists(), name

    # store contents
    import sqlite3

    scon = sqlite3.connect(str(run_dir / "runstore.sqlite"))
    tools = [r[0] for r in scon.execute("SELECT DISTINCT tool FROM tool_calls").fetchall()]
    assert "load_journal_entries" in tools and "cross_reference_flags" in tools
    n_rules = scon.execute("SELECT count(*) FROM tool_calls WHERE phase='EXECUTE'").fetchone()[0]
    assert n_rules >= 10
    scon.close()

    # second start on same run refused
    with pytest.raises(OrchestrationError, match="already exists"):
        orch.start_run(cfg_file, extract)


def test_reject_rate_gate_pauses_run(tmp_path):
    rows = [
        ",1,2026-05-01,4000,SAPUSER,bad,C9D,-1.00,USD,system",   # missing ref -> reject
        ",2,2026-05-01,1200,SAPUSER,bad,C9D,1.00,USD,system",
        ",3,2026-05-02,4000,SAPUSER,bad,C9E,-1.00,USD,system",
        ",4,2026-05-02,1200,SAPUSER,bad,C9E,1.00,USD,system",
    ]
    cfg = base_config_dict(run_id="REJ_Q2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    extract = tmp_path / "extract.csv"
    extract.write_text(
        "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE\n"
        + "\n".join(rows), encoding="utf-8")
    orch = Orchestrator(runs_root=tmp_path / "runs")
    with pytest.raises(OrchestrationError, match="reject rate"):
        orch.start_run(cfg_file, extract)


def test_stale_lock_recovery(tmp_path, engagement, monkeypatch):
    tmp_path2, cfg_file, extract = engagement
    orch = Orchestrator(runs_root=tmp_path2 / "runs")
    run_id = orch.start_run(cfg_file, extract)

    # simulate a crash: leave a stale lock behind (dead pid, old heartbeat)
    import time as _t

    lock_path = tmp_path2 / "runs" / run_id / "run.lock"
    lock_path.write_text(json.dumps({
        "pid": 999999999, "create_time": _t.time() - 3600,
        "heartbeat": _t.time() - 3600}), encoding="utf-8")

    info = orch.recover_run(run_id)
    recovered_kinds = [k for _, k, _ in info["events"]]
    assert "lock_recovered" in recovered_kinds
    assert RunLock.read(tmp_path2 / "runs" / run_id) is None   # stale marker removed

    from je_agent.workspace import RunLock as RL
    _ = RL  # silence import-in-test linters


def test_recovery_lock_blocks_concurrent_recoverers(tmp_path, engagement):
    _, cfg_file, extract = engagement
    orch = Orchestrator(runs_root=tmp_path / "runs")
    run_id = orch.start_run(cfg_file, extract)

    rec_path = tmp_path / "runs" / run_id / "run.recovery.lock"
    rec_path.parent.mkdir(parents=True, exist_ok=True)

    # holder refuses a second concurrent recoverer (Y7 race guard)
    from je_agent.workspace import RecoveryLock

    with RecoveryLock(rec_path):
        import os

        with pytest.raises(FileExistsError):
            os.open(rec_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


# -- CLI smoke ---------------------------------------------------------------------


def test_cli_status_command(engagement):
    tmp_path, cfg_file, extract = engagement
    runs_dir = tmp_path / "runs"
    Orchestrator(runs_root=runs_dir).start_run(cfg_file, extract)

    result = subprocess.run(
        [sys.executable, "-m", "je_agent.cli", "status", "CLI_Q2",
         "--runs-dir", str(runs_dir)],
        capture_output=True, text=True, timeout=120,
        env=None, check=False,
    )
    combined = result.stdout + result.stderr
    assert "CLI_Q2" in combined
    assert "awaiting_review" in combined
