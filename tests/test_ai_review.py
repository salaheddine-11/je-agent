"""Feature 2 tests: AI reviewer decision mapping + confidence floor."""

from __future__ import annotations

import duckdb
import pytest
from pathlib import Path

from je_agent.ai_review import _decision_for
from je_agent.config import load_config
from je_agent.run_context import RunContext
from je_agent.schemas import EntryAssessment
from je_agent.store import RunStore


def _cfg(tmp_path, **overrides):
    import yaml
    base = {
        "run_id": "AIREV_Q1", "period_end": "2026-06-30",
        "materiality": {"overall": 1, "performance": 1, "currency": "USD"},
        "source": {"system": "generic", "amount_column": "A",
                   "column_map": {"posting_date": "D", "account": "C",
                                  "username": "U", "description": "T", "entry_ref": "R"}},
        "reviewer": {"name": "jdoe"},
    }
    cfg = dict(base)
    for k, v in overrides.items():
        cfg = _merge(cfg, k, v)
    if tmp_path is None:
        # mapping tests: build config in-memory from a temp file under system tmp
        import tempfile
        tmp_path = Path(tempfile.mkdtemp())
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return load_config(path)


def _merge(cfg, dotted, val):
    parts = dotted.split(".")
    node = cfg
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = val
    return cfg


def test_accept_when_low_concern():
    a = EntryAssessment(entry_ref="X", rationale_concern="low",
                        concern_note="routine", recommended_action="accept_flag", priority=2)
    d, reason, conf = _decision_for(a, _cfg(tmp_path=None))
    assert d == "accept"
    assert "routine" in reason
    assert conf == 0.9


def test_high_concern_always_inspect():
    a = EntryAssessment(entry_ref="X", rationale_concern="high",
                        concern_note="year-end manual", recommended_action="accept_flag", priority=5)
    d, _, conf = _decision_for(a, _cfg(tmp_path=None))
    assert d == "inspect"
    assert conf == 0.95


def test_inspect_recommendation_maps_inspect():
    a = EntryAssessment(entry_ref="X", rationale_concern="medium",
                        concern_note="vouch", recommended_action="inspect", priority=3)
    d, _, _ = _decision_for(a, _cfg(tmp_path=None))
    assert d == "inspect"


def test_confidence_floor_rounds_ai_default(tmp_path):
    # a low-confidence path (no clear recommendation) under a high threshold
    cfg = _cfg(tmp_path, **{"review.ai_min_confidence": 0.95})
    a = EntryAssessment(entry_ref="X", rationale_concern="none",
                        concern_note="no note", recommended_action="override", priority=1)
    d, _, conf = _decision_for(a, cfg)
    assert conf < cfg.review.ai_min_confidence
    # run_ai_review bypasses to default when confidence < floor
    from je_agent.ai_review import run_ai_review
    assert cfg.review.ai_default_decision in ("inspect", "accept")
