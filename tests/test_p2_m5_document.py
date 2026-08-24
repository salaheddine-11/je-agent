"""P2-M5 tests: facts block, citation validation (C1), finalize gates 1-4, workpaper."""

from __future__ import annotations

import duckdb
import pytest

from je_agent.config import load_config
from je_agent.document import (
    BASE_LIMITATIONS,
    build_facts_block,
    build_workpaper,
    finalize_gates,
    validate_citations,
)
from je_agent.ingest import ingest_extract
from je_agent.review import (
    DecisionInput,
    acknowledge_dq_warnings,
    submit_decisions,
)
from je_agent.rules import execute_rules
from je_agent.run_context import RunContext
from je_agent.schemas import Narrative, TriageReport
from je_agent.store import RunStore
from je_agent.universe import UniverseSelection
from tests.conftest import base_config_dict, write_config

HEADER = "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE"


def setup_world(tmp_path):
    cfg = base_config_dict(run_id="DOC_Q2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    rows = []
    for i in range(3):
        amt = 300000 + i * 1007
        rows += [
            f"D{i},1,2026-06-15,6100,JDOE,fee,D{i}D,-{amt}.00,USD,manual",
            f"D{i},2,2026-06-15,1000,JDOE,fee,D{i}D,{amt}.00,USD,manual",
            f"S{i},1,2026-05-05,4000,SAPUSER,sales,S{i}D,-900.00,USD,system",
            f"S{i},2,2026-05-05,1200,SAPUSER,sales,S{i}D,900.00,USD,system",
        ]
    extract = tmp_path / "extract.csv"
    extract.write_text("\n".join([HEADER] + rows), encoding="utf-8")
    ctx = RunContext.create(tmp_path / "runs", "DOC_Q2",
                            (tmp_path / "config.yaml").read_text(encoding="utf-8"), extract)
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    execute_rules(con, config)
    from je_agent.crossref import cross_reference_flags

    cross_reference_flags(con)
    store = RunStore(ctx.runstore_path)
    universe = UniverseSelection(
        entries=[{"entry_ref": r[0], "rules_hit": 3, "abs_amount": float(r[1]),
                  "currency": "USD", "selection_basis": "targeted"}
                 for r in con.execute(
                     "SELECT DISTINCT entry_ref, abs_amount FROM xref_ranked "
                     "WHERE entry_ref LIKE 'D%'").fetchall()],
        total_flagged=3, selected=3)
    return con, config, store, universe


def good_narrative(facts):
    return Narrative.model_validate({
        "title": "JE Testing — DOC_Q2",
        "sections": [
            {"heading": "Population",
             "text": (f"We tested [fact:population_lines] lines; [fact:flagged_documents] documents "
                      f"flagged; universe capped at [fact:universe_size].")},
            {"heading": "Outcomes",
             "text": ("Inspect [fact:decisions_inspect], accept [fact:decisions_accept], "
                      "override [fact:decisions_override].")},
        ],
        "cited_fact_keys": ["population_lines", "flagged_documents", "universe_size",
                            "decisions_inspect", "decisions_accept", "decisions_override"],
    })


# ---------------------------------------------------------------------------
# citation validation (C1)
# ---------------------------------------------------------------------------


def test_citations_valid_on_good_narrative():
    facts = {k: "1" for k in ("population_lines", "flagged_documents", "universe_size",
                              "decisions_inspect", "decisions_accept", "decisions_override")}
    n = good_narrative(facts)
    assert validate_citations(n, facts) == []


def test_unknown_citation_rejected():
    facts = {k: "1" for k in ("population_lines", "flagged_documents", "universe_size",
                              "decisions_inspect", "decisions_accept", "decisions_override")}
    n = Narrative.model_validate({
        "title": "t",
        "sections": [{"heading": "h",
                      "text": "We saw [fact:made_up_key] and [fact:population_lines]."}],
        "cited_fact_keys": ["made_up_key", "population_lines"],
    })
    problems = validate_citations(n, facts)
    assert any("do not resolve" in p for p in problems)


def test_missing_required_citation_rejected():
    facts = {"population_lines": "10"}
    n = Narrative.model_validate({
        "title": "t",
        "sections": [{"heading": "h", "text": "Only [fact:population_lines] cited."}],
        "cited_fact_keys": ["population_lines"],
    })
    problems = validate_citations(n, facts)
    assert any("required facts not cited" in p for p in problems)


def test_section_without_any_citation_rejected():
    facts = {k: "1" for k in ("population_lines", "flagged_documents", "universe_size",
                              "decisions_inspect", "decisions_accept", "decisions_override")}
    n = Narrative.model_validate({
        "title": "t",
        "sections": [
            {"heading": "a", "text": "[fact:population_lines] lines."},
            {"heading": "b", "text": "No citations here at all."},
        ],
        "cited_fact_keys": ["population_lines"],
    })
    problems = validate_citations(n, facts)
    assert any("cites no" in p for p in problems)


# ---------------------------------------------------------------------------
# finalize gates 1-4
# ---------------------------------------------------------------------------


def test_all_gates_pass_after_full_review(tmp_path):
    con, config, store, universe = setup_world(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)

    # reviewer decides every universe entry
    submit_decisions(store, "DOC_Q2", "jdoe", "declared",
                     [DecisionInput(entry_ref=e["entry_ref"], decision="accept")
                      for e in universe.entries])

    narrative = good_narrative(facts)
    report = finalize_gates(con, config, universe, narrative, facts, store,
                            accepted_limitations=set(), procedure_failures={})
    assert report.all_passed, report.problems


def test_gate1_blocks_when_decision_missing(tmp_path):
    con, config, store, universe = setup_world(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)
    narrative = good_narrative(facts)
    # decide only one entry
    submit_decisions(store, "DOC_Q2", "jdoe", "declared",
                     [DecisionInput(entry_ref=universe.entries[0]["entry_ref"],
                                    decision="accept")])
    report = finalize_gates(con, config, universe, narrative, facts, store,
                            set(), {})
    assert not report.gate1_review_complete
    assert any("gate1" in p for p in report.problems)


def test_gate2_requires_gap_acknowledgment_for_failed_procedure(tmp_path):
    con, config, store, universe = setup_world(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)
    narrative = good_narrative(facts)
    submit_decisions(store, "DOC_Q2", "jdoe", "declared",
                     [DecisionInput(entry_ref=e["entry_ref"], decision="accept")
                      for e in universe.entries])

    failures = {"reversals": "internal error"}
    report = finalize_gates(con, config, universe, narrative, facts, store,
                            set(), failures)
    assert not report.gate2_procedures_complete

    # with the gap logged as an accepted limitation -> passes
    report2 = finalize_gates(con, config, universe, narrative, facts, store,
                             accepted_limitations={"reversals"}, procedure_failures=failures)
    assert report2.gate2_procedures_complete


def test_gate4_blocks_unaccepted_dynamic_limitations(tmp_path):
    from tests.conftest import write_config

    # force the currency-stratified fallback => dynamic limitations exist
    rows = []
    for i in range(4):
        amt = 300000 + i * 1007
        rows.append(f"D{i},1,2026-06-15,6100,JDOE,fee,D{i}D,-{amt}.00,USD,manual")
        rows.append(f"D{i},2,2026-06-15,1000,JDOE,fee,D{i}D,{amt}.00,USD,manual")
    for i in range(3):
        amt = 400000 + i * 1013
        rows.append(f"ER{i},1,2026-06-15,6100,MARTIN_B,eur fee,ER{i}D,-{amt}.00,EUR,manual")
        rows.append(f"ER{i},2,2026-06-15,1000,MARTIN_B,eur fee,ER{i}D,{amt}.00,EUR,manual")

    cfg = base_config_dict(run_id="DOC_Q2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    extract = tmp_path / "extract.csv"
    extract.write_text("\n".join([HEADER] + rows), encoding="utf-8")
    ctx = RunContext.create(tmp_path / "runs", "DOC_Q2",
                            (tmp_path / "config.yaml").read_text(encoding="utf-8"), extract)
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    execute_rules(con, config)
    from je_agent.crossref import cross_reference_flags
    from je_agent.universe import select_universe

    cross_reference_flags(con)
    universe = select_universe(con, config)   # no fx => fallback
    assert universe.fallback_used

    store = RunStore(ctx.runstore_path)
    facts = build_facts_block(con, config, universe, None, store)
    narrative = good_narrative(facts)
    submit_decisions(store, "DOC_Q2", "jdoe", "declared",
                     [DecisionInput(entry_ref=e["entry_ref"], decision="accept")
                      for e in universe.entries])

    active = finalize_gates  # noqa: readability
    report = finalize_gates(con, config, universe, narrative, facts, store,
                            set(), {})
    assert not report.gate4_limitations_accepted
    assert any("currency_stratified_fallback" in p for p in report.problems)

    # accept ALL active limitations -> gate 4 passes
    from je_agent.document import active_limitations

    all_active = set(active_limitations(con, config, universe))
    report2 = finalize_gates(con, config, universe, narrative, facts, store,
                             all_active, {})
    assert report2.gate4_limitations_accepted


# ---------------------------------------------------------------------------
# workpaper assembly
# ---------------------------------------------------------------------------


def test_workpaper_contains_mandatory_sections(tmp_path):
    con, config, store, universe = setup_world(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)
    narrative = good_narrative(facts)
    acknowledge_dq_warnings(store, "DOC_Q2", "jdoe", "declared",
                            [{"warning_id": "dq_missing_fields",
                              "reason": "descriptions optional in this ERP export"}])
    wp = build_workpaper(None, config, facts, narrative, store,
                         limitations_accepted={"currency_stratified_fallback"})
    assert len(wp["scope_and_limitations"]["base"]) >= len(BASE_LIMITATIONS)
    assert wp["dq_appendix"] and wp["dq_appendix"][0][0] == "dq_missing_fields"
    assert wp["ai_governance"]["chain_integrity_verified"] is True
    assert any("flagged_documents=" in s["text"] for s in wp["narrative_sections"])
