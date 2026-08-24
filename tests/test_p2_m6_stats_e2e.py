"""P2-M6 + Phase 2 capstone: statistics tools, representative sampling, and the
full INGEST→…→DOCUMENT pipeline with FakeProvider (§9.3 E2E)."""

from __future__ import annotations

import duckdb
import pytest

from je_agent.config import load_config
from je_agent.crossref import cross_reference_flags
from je_agent.document import build_facts_block, finalize_gates, active_limitations
from je_agent.ingest import ingest_extract
from je_agent.llm.provider import FakeProvider, ProviderResponse, ToolCall
from je_agent.review import DecisionInput, submit_decisions
from je_agent.rules import execute_rules
from je_agent.run_context import RunContext
from je_agent.schemas import Narrative
from je_agent.stats import run_benford, run_outlier_detection, sample_representative
from je_agent.store import RunStore
from je_agent.triage import run_triage
from je_agent.universe import select_universe
from tests.conftest import base_config_dict, write_config

HEADER = "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE"


def build_world(tmp_path, n_docs: int = 30):
    cfg = base_config_dict(run_id="E2E_P2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg["representative_sample"] = {"enabled": True, "size": 6,
                                    "strata": ["month", "entry_type"]}
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)

    rows = []
    for i in range(n_docs):
        amt = 300000 + i * 997          # above PM=175000 -> all flagged manual docs join universe
        m = i % 9 + 1
        rows.append(f"D{i},1,2026-0{m}-15,6100,JDOE,fee,D{i}D,-{amt}.00,USD,manual")
        rows.append(f"D{i},2,2026-0{m}-15,1000,JDOE,fee,D{i}D,{amt}.00,USD,manual")
        rows.append(f"S{i},1,2026-0{m}-10,4000,SAPUSER,sales,S{i}D,-900.00,USD,system")
        rows.append(f"S{i},2,2026-0{m}-10,1200,SAPUSER,sales,S{i}D,900.00,USD,system")
    extract = tmp_path / "extract.csv"
    extract.write_text("\n".join([HEADER] + rows), encoding="utf-8")

    ctx = RunContext.create(tmp_path / "runs", "E2E_P2",
                            (tmp_path / "config.yaml").read_text(encoding="utf-8"), extract)
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    results = execute_rules(con, config)
    cross_reference_flags(con)
    store = RunStore(ctx.runstore_path)
    return ctx, con, config, store, results


def test_benford_informational_with_seed(tmp_path):
    _, con, config, _, _ = build_world(tmp_path)
    out = run_benford(con, config.run_id)
    assert out["informational_only"] is True
    assert "never gate" in out["limitation"]
    if out.get("mad") is not None:
        assert out["nigrini_assessment"] in (
            "close conformity", "acceptable conformity",
            "marginally acceptable", "nonconformity")


def test_outlier_seeded_and_deterministic(tmp_path):
    _, con, config, _, _ = build_world(tmp_path)
    a = run_outlier_detection(con, config)
    b = run_outlier_detection(con, config)
    assert a["seed"] == b["seed"]
    assert a["outliers"] == b["outliers"]
    assert all(abs(o["z"]) >= a["z_threshold"] for o in a["outliers"])


def test_representative_sample_joins_universe(tmp_path):
    _, con, config, _, _ = build_world(tmp_path)
    sel_before = select_universe(con, config)
    targeted_n = sel_before.selected

    sample = sample_representative(con, config)
    assert sample["selected"] > 0
    assert "non_projection_statement" in sample

    # representative entries appear in xref_ranked tagged 'representative'
    n_repr = con.execute(
        "SELECT count(*) FROM xref_ranked WHERE selection_basis='representative'"
    ).fetchone()[0]
    assert n_repr >= sample["selected"] - 2      # overlap with targeted allowed

    sel_after = select_universe(con, config)
    bases = {e["selection_basis"] for e in sel_after.entries}
    assert "targeted" in bases
    assert sel_after.selected >= targeted_n


# ---------------------------------------------------------------------------
# CAPSTONE: full pipeline, FakeProvider triage, decisions, gates green
# ---------------------------------------------------------------------------


class ScriptedTriage(FakeProvider):
    """Assesses every entry in the rendered pack, first doc high, rest low."""

    def complete(self, system, turns, tools_spec):
        brief = next(t.content for t in turns if t.role == "user" and "entry_ref:" in t.content)
        import re

        refs = sorted(set(re.findall(r"DOCUMENT \d+ of \d+ — entry_ref: (\S+)", brief)))
        assessments = [{
            "entry_ref": r,
            "rationale_concern": "high" if i == 0 else "low",
            "concern_note": "routine consulting fee" if i else "largest in pack; verify support",
            "recommended_action": "inspect" if i == 0 else "accept_flag",
            "priority": 4 if i == 0 else 2,
        } for i, r in enumerate(refs)]
        return ProviderResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall(id=f"tc_{len(refs)}_{id(turns) % 9999}",
                                 name="submit_pack_assessment",
                                 arguments={"assessments": assessments,
                                            "pack_summary": "assessed"})],
            model_id="fake/capstone")


def test_full_pipeline_ingest_to_finalized_gates(tmp_path):
    ctx, con, config, store, rule_results = build_world(tmp_path)

    # EXECUTE record-keeping parity with orchestrator (facts read from store)
    for r in rule_results:
        if type(r).__name__ == "RuleResult":
            store.record_tool_call("E2E_P2", store.next_seq("E2E_P2"), "EXECUTE", r.rule,
                                   {}, "ok", result={"flagged": r.flagged})

    # TRIAGE over the universe
    universe = select_universe(con, config)
    report = run_triage(con, config, ScriptedTriage([]), universe, store, "E2E_P2")
    assert report.universe_covered == universe.selected

    # REVIEW: decide everything the way the triage suggests
    from je_agent.review import effective_decisions as _eff  # noqa: F401

    decisions = []
    for a in report.assessments:
        action = {"inspect": "inspect", "accept_flag": "accept",
                  "override": "override"}[a.recommended_action]
        decisions.append(DecisionInput(entry_ref=a.entry_ref, decision=action,
                                       reason="capstone" if action == "override" else None))
    submit_decisions(store, "E2E_P2", "jdoe", "declared", decisions)

    # DOCUMENT: facts + narrative + gates
    facts = build_facts_block(con, config, universe, report, store)
    narrative = Narrative.model_validate({
        "title": "JE Testing E2E",
        "sections": [
            {"heading": "Scope",
             "text": ("Population [fact:population_lines] lines; [fact:flagged_documents] "
                      "flagged docs; universe [fact:universe_size] "
                      "(basis [fact:selection_basis]).")},
            {"heading": "Results",
             "text": ("Inspect [fact:decisions_inspect]; accept [fact:decisions_accept]; "
                      "override [fact:decisions_override]. Manual rule hits: "
                      "[fact:rule_manual_entries]. Followups [fact:followups_recorded].")},
        ],
        "cited_fact_keys": list(facts.keys()),
    })

    from je_agent.document import validate_citations

    assert validate_citations(narrative, facts) == []

    gates = finalize_gates(con, config, universe, narrative, facts, store,
                           accepted_limitations=set(), procedure_failures={})
    assert gates.all_passed, gates.problems

    # chain integrity across all three review tables
    from je_agent.review import verify_all_chains

    chains = verify_all_chains(store, "E2E_P2")
    assert all(c.intact for c in chains.values())
    assert chains["review_decisions"].length == len(decisions)


def test_gate3_rejects_unresolved_citation_in_real_flow(tmp_path):
    ctx, con, config, store, _ = build_world(tmp_path, n_docs=5)
    universe = select_universe(con, config)
    report = run_triage(con, config, ScriptedTriage([]), universe, store, "E2E_P2")
    submit_decisions(store, "E2E_P2", "jdoe", "declared",
                     [DecisionInput(entry_ref=a.entry_ref, decision="accept")
                      for a in report.assessments])
    facts = build_facts_block(con, config, universe, report, store)

    bad = Narrative.model_validate({
        "title": "bad",
        "sections": [{"heading": "h",
                      "text": "[fact:population_lines] lines; invented [fact:bogus_stat]."}],
        "cited_fact_keys": ["population_lines", "bogus_stat"],
    })
    gates = finalize_gates(con, config, universe, bad, facts, store, set(), {})
    assert not gates.gate3_citations_valid
