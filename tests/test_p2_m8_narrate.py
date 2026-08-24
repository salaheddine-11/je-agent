"""NARRATE phase tests: facts -> cited narrative through the gated loop (C1)."""

from __future__ import annotations

import duckdb
import pytest

from je_agent.config import load_config
from je_agent.document import build_facts_block, validate_citations
from je_agent.ingest import ingest_extract
from je_agent.llm.provider import FakeProvider, ProviderResponse, ToolCall
from je_agent.narrate import run_narrate
from je_agent.run_context import RunContext
from je_agent.schemas import Narrative
from je_agent.store import RunStore
from tests.conftest import base_config_dict, write_config

HEADER = "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE"


def setup(tmp_path):
    cfg = base_config_dict(run_id="NAR_Q2")
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    rows = [
        "N1,1,2026-06-15,6100,JDOE,fee,N1D,-300007.00,USD,manual",
        "N1,2,2026-06-15,1000,JDOE,fee,N1D,300007.00,USD,manual",
    ]
    extract = tmp_path / "extract.csv"
    extract.write_text("\n".join([HEADER] + rows), encoding="utf-8")
    ctx = RunContext.create(tmp_path / "runs", "NAR_Q2",
                            (tmp_path / "config.yaml").read_text(encoding="utf-8"), extract)
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    execute_rules(con, config) if (execute_rules := __import__(
        "je_agent.rules", fromlist=["execute_rules"]).execute_rules) else None
    from je_agent.crossref import cross_reference_flags

    cross_reference_flags(con)
    store = RunStore(ctx.runstore_path)
    from je_agent.universe import select_universe

    universe = select_universe(con, config)
    return con, config, store, universe, ctx


def good_narrative(facts_keys):
    keys = list(facts_keys)
    text = ("We tested [fact:population_lines] lines; [fact:flagged_documents] flagged; "
            "[fact:universe_size] universe; outcomes [fact:decisions_inspect]/"
            "[fact:decisions_accept]/[fact:decisions_override].")
    return {
        "title": "Narrative",
        "sections": [{"heading": "All", "text": text}],
        "cited_fact_keys": keys,
    }


def test_narrate_produces_cited_narrative_and_persists(tmp_path):
    con, config, store, universe, ctx = setup(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)

    class P(FakeProvider):
        def complete(self, system, turns, tools_spec):
            brief = next(t.content for t in turns if t.role == "user")
            # cite every fact the brief lists as required + present in facts
            import re

            required = re.search(r"Required facts to cite: (.+)", brief).group(1).split(", ")
            args = good_narrative(facts.keys())
            # ensure required all cited in text too
            extra = " ".join(f"[fact:{k}]" for k in required if f"[fact:{k}]" not in
                             args["sections"][0]["text"])
            args["sections"][0]["text"] += " " + extra
            args["cited_fact_keys"] = sorted(set(facts.keys()) | set(required))
            return ProviderResponse(
                stop_reason="tool_use",
                tool_calls=[ToolCall(name="submit_narrative", arguments=args)],
                model_id="fake")

    save_to = ctx.llm_dir / "narrative.json"
    res = run_narrate(con, config, P([]), universe, store, "NAR_Q2",
                      triage_summary="routine", save_to=save_to)

    assert save_to.exists()
    reloaded = Narrative.model_validate_json(save_to.read_text(encoding="utf-8"))
    assert validate_citations(reloaded, facts) == []


def test_narrate_repair_on_bad_citation_then_success(tmp_path):
    con, config, store, universe, ctx = setup(tmp_path)
    facts = build_facts_block(con, config, universe, None, store)

    bad = {"title": "t",
           "sections": [{"heading": "h", "text": "cite [fact:nope_key]."}],
           "cited_fact_keys": ["nope_key"]}
    good = good_narrative(facts.keys())
    good["sections"][0]["text"] += " " + " ".join(
        f"[fact:{k}]" for k in ["flagged_documents", "universe_size", "decisions_inspect",
                                "decisions_accept", "decisions_override"])
    good["cited_fact_keys"] = sorted(set(good["cited_fact_keys"]) | set(facts.keys()))

    provider = FakeProvider([
        {"tool": "submit_narrative", "args": bad},
        {"tool": "submit_narrative", "args": good},
    ])
    res = run_narrate(con, config, provider, universe, store, "NAR_Q2")
    assert res.artifact is not None and res.turns_used == 2


def test_narrate_double_failure_is_loud(tmp_path):
    con, config, store, universe, ctx = setup(tmp_path)
    bad = {"title": "t",
           "sections": [{"heading": "h", "text": "cite [fact:nope_key]."}],
           "cited_fact_keys": ["nope_key"]}
    provider = FakeProvider([{"tool": "submit_narrative", "args": bad}] * 5)
    from je_agent.phase_runner import PhaseFailure

    with pytest.raises(PhaseFailure, match="twice"):
        run_narrate(con, config, provider, universe, store, "NAR_Q2")
