"""E2E: review.mode=ai — config -> triage -> AI review -> narrate -> gates -> report,
no human decisions. Uses a scripted FakeProvider so it's deterministic and offline."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from je_agent.llm.provider import FakeProvider, ProviderResponse, ToolCall


class ScriptedTriage(FakeProvider):
    """Assess every entry in the pack as low-concern accept_flag (enables AI review)."""

    def complete(self, system, turns, tools_spec):
        brief = next(t.content for t in turns if t.role == "user" and "entry_ref:" in t.content)
        import re

        refs = sorted(set(re.findall(r"DOCUMENT \d+ of \d+ — entry_ref: (\S+)", brief)))
        assessments = [{
            "entry_ref": r, "rationale_concern": "low",
            "concern_note": "routine, documented posting",
            "recommended_action": "accept_flag", "priority": 2,
        } for r in refs]
        return ProviderResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall(id=f"tc_{len(refs)}_{id(turns) % 9999}",
                                 name="submit_pack_assessment",
                                 arguments={"assessments": assessments,
                                            "pack_summary": "assessed"})],
            model_id="fake/airev")


class ScriptedNarrate(FakeProvider):
    """Emit a citation-valid narrative covering every required fact key."""

    def complete(self, system, turns, tools_spec):
        sections = [{"heading": "Findings",
                     "text": "Tested [fact:population_lines] lines across "
                             "[fact:flagged_documents] flagged documents; "
                             "[fact:universe_size] reviewed; "
                             "[fact:decisions_inspect] inspect, "
                             "[fact:decisions_accept] accept, "
                             "[fact:decisions_override] override."}]
        keys = ["population_lines", "flagged_documents", "universe_size",
                "decisions_inspect", "decisions_accept", "decisions_override"]
        return ProviderResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall(
                id="nar_1", name="submit_narrative",
                arguments={"title": "AI-reviewed engagement",
                           "sections": sections, "cited_fact_keys": keys})],
            model_id="fake/airev")


def build_world(tmp_path, run_id="AIE2E_Q1", mode="ai"):
    import yaml
    from je_agent.config import load_config
    from je_agent.run_context import RunContext

    # paired debit+credit lines (balance), amount above PM 70 -> join universe
    rows = []
    for i in range(12):
        amt = 300000 + i * 997
        m = i % 9 + 1
        rows.append(f"D{i},1,2026-0{m}-15,6100,JD,fee,D{i}D,-{amt}.00,USD,manual")
        rows.append(f"D{i},2,2026-0{m}-15,1000,JD,fee,D{i}D,{amt}.00,USD,manual")
    extract = ("REF,LINE,DATE,ACCT,USER,DESC,REF2,VAL,CUR,TYPE\n" + "\n".join(rows))

    cfg = {
        "run_id": run_id, "period_end": "2026-06-30",
        "materiality": {"overall": 100, "performance": 70, "currency": "USD"},
        "source": {"system": "generic", "amount_column": "VAL", "currency_column": "CUR",
                   "column_map": {"posting_date": "DATE", "account": "ACCT",
                                  "username": "USER", "description": "DESC",
                                  "source_doc": "REF", "entry_ref": "REF",
                                  "document_date": "DATE", "entry_created_date": "DATE",
                                  "entry_type": "TYPE"}},
        "review": {"max_universe_size": 40, "overflow_policy": "stratify",
                   "pack_size": 20, "mode": mode, "ai_min_confidence": 0.6},
        "llm_privacy": {"mode": "zero_retention", "pii_scrubbing": True},
        "reviewer": {"name": "jdoe"},
    }
    cpath = tmp_path / "config.yaml"
    cpath.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    config = load_config(cpath)

    epath = tmp_path / "extract.csv"
    epath.write_text(extract, encoding="utf-8")
    ctx = RunContext.create(tmp_path / "runs", run_id, cpath.read_text(), epath)

    from je_agent.ingest import ingest_extract
    from je_agent.rules import execute_rules
    from je_agent.crossref import cross_reference_flags

    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    execute_rules(con, config)
    cross_reference_flags(con)
    from je_agent.store import RunStore

    store = RunStore(ctx.runstore_path)
    store.record_run(config.run_id, "e2e", "0.1.0", config.model_dump(mode="json"))
    return ctx, con, config, store


def test_ai_review_full_auto(tmp_path):
    from je_agent.universe import select_universe
    from je_agent.triage import run_triage
    from je_agent.ai_review import run_ai_review
    from je_agent.review import effective_decisions
    from je_agent.document import build_facts_block, finalize_gates, active_limitations

    ctx, con, config, store = build_world(tmp_path)
    universe = select_universe(con, config)
    triage = run_triage(con, config, ScriptedTriage([]), universe, store, config.run_id,
                        save_to=ctx.llm_dir / "triage_report.json")
    assert triage.universe_covered == universe.selected

    res = run_ai_review(store, config, universe, triage)
    assert res["recorded"] == universe.selected
    assert len(set(res["decisions"].values())) == 1  # all accept (low concern)

    eff = effective_decisions(store, config.run_id)
    assert len(eff) == universe.selected
    for ref, d in eff.items():
        assert d["decision"] == "accept"
        assert d["reviewer"] == "ai-reviewer"

    # narrate + gates (auto path uses run_narrate then gates)
    from je_agent.narrate import run_narrate

    nar = run_narrate(con, config, ScriptedNarrate([]), universe, store, config.run_id,
                      triage_summary=json.dumps({"summary": "low"}),
                      save_to=ctx.llm_dir / "narrative.json")
    facts = build_facts_block(con, config, universe, None, store)
    accepted = set(active_limitations(con, config, universe))
    gates = finalize_gates(con, config, universe, nar.artifact, facts, store,
                           accepted_limitations=accepted, procedure_failures={})
    assert gates.all_passed


def test_review_mode_defaults_human(tmp_path):
    import yaml
    from je_agent.config import load_config

    cfg = {
        "run_id": "HUM_Q1", "period_end": "2026-06-30",
        "materiality": {"overall": 1, "performance": 1, "currency": "USD"},
        "source": {"system": "generic", "amount_column": "A",
                   "column_map": {"posting_date": "D", "account": "C",
                                  "username": "U", "description": "T", "entry_ref": "R"}},
        "reviewer": {"name": "jdoe"},
    }
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    c = load_config(p)
    assert c.review.mode == "human"
    assert c.review.ai_default_decision == "inspect"
