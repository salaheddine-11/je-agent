"""M0 smoke tests: config load/freeze, canonical order, hashing, workspace."""

from __future__ import annotations

import time

import pytest

from je_agent.config import (
    CANONICAL_RULE_ORDER,
    canonical_rule_sort,
    freeze_config,
    load_config,
)
from je_agent.hashing import ChainReport, genesis_row_hash, row_hash, verify_chain
from je_agent.run_context import RunContext
from je_agent.workspace import LockError, RecoveryLock, RunLock


# -- config ------------------------------------------------------------------


def test_load_and_freeze_roundtrip(config_file):
    cfg = load_config(config_file)
    assert cfg.period_end == "2026-06-30"
    assert cfg.materiality.performance == 175000
    assert cfg.rule_params.split_threshold == 10000          # v1.6 Z7 default
    assert "SAP*" in cfg.rule_params.system_user_patterns    # v1.6 Z3 defaults

    yaml_text, digest = freeze_config(cfg)
    assert len(digest) == 64
    frozen = config_file.parent / "frozen.yaml"
    frozen.write_text(yaml_text, encoding="utf-8")
    cfg2 = load_config(frozen)
    _, digest2 = freeze_config(cfg2)
    assert digest == digest2  # freeze is stable


def test_performance_must_not_exceed_overall(tmp_path):
    from tests.conftest import base_config_dict, write_config

    bad = base_config_dict()
    bad["materiality"]["performance"] = 300000
    f = write_config(tmp_path / "bad.yaml", bad)
    with pytest.raises(ValueError):
        load_config(f)


# -- canonical order (Z2) ------------------------------------------------------


def test_canonical_order_is_stable_under_input_permutations():
    plan_a = ["reversals", "manual_entries", "unusual_pairs"]
    plan_b = ["unusual_pairs", "reversals", "manual_entries"]
    assert canonical_rule_sort(plan_a) == canonical_rule_sort(plan_b)
    assert canonical_rule_sort(plan_a)[0] == "manual_entries"
    assert canonical_rule_sort(list(CANONICAL_RULE_ORDER)) == list(CANONICAL_RULE_ORDER)


def test_canonical_sort_rejects_unknown_rules():
    with pytest.raises(ValueError, match="unknown rule"):
        canonical_rule_sort(["manual_entries", "made_up_rule"])


# -- hash chains (Z6) -----------------------------------------------------------


def test_genesis_hash_deterministic():
    payload = {"a": 1, "b": "x"}
    assert genesis_row_hash(payload) == genesis_row_hash({"b": "x", "a": 1})  # key order irrelevant


def test_verify_chain_intact_and_tampered():
    rows = []
    prev = "0" * 64
    for i in range(5):
        payload = {"i": i, "decision": "accept" if i % 2 else "inspect"}
        h = row_hash(prev, payload)
        rows.append({**payload, "row_hash": h})
        prev = h

    report = verify_chain(rows, table="review_decisions", run_id="r1")
    assert isinstance(report, ChainReport)
    assert report.intact and report.length == 5

    tampered = [dict(r) for r in rows]
    tampered[2]["decision"] = "override"  # flip history
    report2 = verify_chain(tampered, table="review_decisions", run_id="r1")
    assert not report2.intact
    assert report2.first_bad_index == 2


# -- workspace + locks ------------------------------------------------------------


def test_run_folder_created_with_frozen_files(tmp_path, clean_extract):
    cfg_yaml = "run_id: TEST\nperiod_end: '2026-06-30'\n"
    ctx = RunContext.create(tmp_path, "TEST", cfg_yaml, clean_extract)
    assert (ctx.dir / "config.yaml").exists()
    assert (ctx.dir / "extract.csv").read_text(encoding="utf-8") == clean_extract.read_text(encoding="utf-8")
    assert len((ctx.dir / "extract.sha256").read_text(encoding="utf-8")) == 64
    with pytest.raises(FileExistsError):
        RunContext.create(tmp_path, "TEST", cfg_yaml, clean_extract)


def test_lock_acquire_release_exclusive(tmp_path):
    lock = RunLock.acquire(tmp_path)
    try:
        data = RunLock.read(tmp_path)
        assert data["pid"] > 0
        assert not RunLock.is_stale(tmp_path)
        with pytest.raises(LockError):
            RunLock.acquire(tmp_path)  # second acquisition refused
    finally:
        lock.release()
    assert RunLock.read(tmp_path) is None


def test_stale_lock_detection_by_dead_pid(tmp_path):
    import json

    dead_payload = {
        "pid": 999999999,               # nobody's pid
        "create_time": time.time() - 10,
        "heartbeat": time.time(),       # fresh heartbeat but owner dead => stale
    }
    (tmp_path / "run.lock").write_text(json.dumps(dead_payload), encoding="utf-8")
    assert RunLock.is_stale(tmp_path)


def test_recovery_lock_single_holder(tmp_path):
    rec = tmp_path / "run.recovery.lock"
    with RecoveryLock(rec):
        assert rec.exists()
        import os

        with pytest.raises(FileExistsError):
            os.open(rec, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # second holder refused
    assert not rec.exists()  # released on exit
