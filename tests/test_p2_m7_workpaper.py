"""P2-M7 tests: triage persistence + workpaper writer + finalize CLI."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from je_agent.cli import app as cli_app
from je_agent.config import load_config
from je_agent.document import build_facts_block, build_workpaper, finalize_gates
from je_agent.ingest import ingest_extract
from je_agent.review import DecisionInput, submit_decisions
from je_agent.rules import execute_rules
from je_agent.run_context import RunContext
from je_agent.schemas import Narrative, TriageReport
from je_agent.store import RunStore
from je_agent.triage import run_triage
from je_agent.universe import select_universe
from je_agent.workpaper import write_workpaper
from tests.conftest import base_config_dict, write_config

HEADER = "ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE"


class OneShotTriage:
    """Minimal provider: assesses every document ref in the brief."""

    def __init__(self):
        self.calls = 0

    def complete(self, system, turns, tools_spec):
        self.calls += 1
        import re

        from je_agent.llm.provider import ProviderResponse, ToolCall

        brief = next(t.content for t in turns if t.role == "user" and "entry_ref:" in t.content)
        refs = sorted(set(re.findall(r"DOCUMENT \d+ of \d+ — entry_ref: (\S+)", brief)))
        return ProviderResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall(name="submit_pack_assessment", arguments={
                "assessments": [{
                    "entry_ref": r, "rationale_concern": "low",
                    "concern_note": "routine", "recommended_action": "accept_flag",
                    "priority": 2} for r in refs],
                "pack_summary": "ok"})],
            model_id="fake")


def setup_run(tmp_path, run_id="WP_Q2"):
    cfg = base_config_dict(run_id=run_id)
    cfg["source"]["column_map"]["entry_ref"] = "ENTRY"
    cfg_file = write_config(tmp_path / "config.yaml", cfg)
    config = load_config(cfg_file)
    rows = []
    for i in range(4):
        amt = 300000 + i * 1007
        rows += [
            f"D{i},1,2026-06-15,6100,JDOE,fee,D{i}D,-{amt}.00,USD,manual",
            f"D{i},2,2026-06-15,1000,JDOE,fee,D{i}D,{amt}.00,USD,manual",
        ]
    extract = tmp_path / "extract.csv"
    extract.write_text("\n".join([HEADER] + rows), encoding="utf-8")
    ctx = RunContext.create(tmp_path / "runs", run_id,
                            (tmp_path / "config.yaml").read_text(encoding="utf-8"), extract)
    ingest_extract(ctx, config)
    con = duckdb.connect(str(ctx.duckdb_path))
    execute_rules(con, config)
    from je_agent.crossref import cross_reference_flags

    cross_reference_flags(con)
    # register the run like the orchestrator would (status lookups depend on it)
    store_tmp = RunStore(ctx.runstore_path)
    from je_agent.ingest import sha256_of_file

    store_tmp.record_run(run_id, sha256_of_file(extract), "0.1.0",
                         config.model_dump(mode="json"))
    store_tmp.close()
    return ctx, con, config


def test_triage_persists_report_json(tmp_path):
    ctx, con, config = setup_run(tmp_path)
    store = RunStore(ctx.runstore_path)
    universe = select_universe(con, config)
    save_to = ctx.llm_dir / "triage_report.json"

    report = run_triage(con, config, OneShotTriage(), universe, store,
                        config.run_id, save_to=save_to)

    assert save_to.exists()
    reloaded = TriageReport.model_validate_json(save_to.read_text(encoding="utf-8"))
    assert reloaded.universe_covered == report.universe_covered == universe.selected


def test_workpaper_writer_produces_all_sheets(tmp_path):
    ctx, con, config = setup_run(tmp_path)
    store = RunStore(ctx.runstore_path)
    universe = select_universe(con, config)
    facts = build_facts_block(con, config, universe, None, store)

    narrative = Narrative.model_validate({
        "title": "t",
        "sections": [{"heading": "Scope",
                      "text": ("[fact:population_lines] lines; [fact:flagged_documents] docs; "
                               "[fact:universe_size] universe; [fact:decisions_inspect] insp; "
                               "[fact:decisions_accept] acc; [fact:decisions_override] ovr.")}],
        "cited_fact_keys": list(facts.keys()),
    })
    wp = build_workpaper(ctx, config, facts, narrative, store,
                         limitations_accepted={"currency_stratified_fallback"})
    out = write_workpaper(tmp_path / "wp.xlsx", wp)

    assert out.exists() and out.stat().st_size > 4000

    # verify sheet contents via openpyxl-free roundtrip: xlsxwriter output readable by duckdb? use zipfile
    import zipfile

    with zipfile.ZipFile(out) as z:
        workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
        expected = ("Summary", "Narrative", "Scope&Limitations", "DQ Appendix",
                    "AI Governance")
        for sheet in expected:
            escaped = sheet.replace("&", "&amp;")
            assert (f'name="{sheet}"' in workbook_xml
                    or f'name="{escaped}"' in workbook_xml), f"{sheet} missing"


def test_finalize_cli_end_to_end(tmp_path):
    ctx, con, config = setup_run(tmp_path)
    store = RunStore(ctx.runstore_path)
    universe = select_universe(con, config)

    # triage + persist + review decisions so gates can pass
    run_triage(con, config, OneShotTriage(), universe, store,
               config.run_id, save_to=ctx.llm_dir / "triage_report.json")
    submit_decisions(store, config.run_id, "jdoe", "declared",
                     [DecisionInput(entry_ref=e["entry_ref"], decision="accept")
                      for e in universe.entries])

    facts = build_facts_block(con, config, universe, None, store)
    narrative = Narrative.model_validate({
        "title": "t",
        "sections": [{"heading": "All",
                      "text": ("[fact:population_lines] [fact:flagged_documents] "
                               "[fact:universe_size] [fact:decisions_inspect] "
                               "[fact:decisions_accept] [fact:decisions_override].")}],
        "cited_fact_keys": list(facts.keys()),
    })
    (ctx.llm_dir / "narrative.json").write_text(narrative.model_dump_json(), encoding="utf-8")
    store.close()
    con.close()

    runner = CliRunner()
    result = runner.invoke(cli_app, ["finalize", config.run_id,
                                     "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    assert (ctx.artifacts_dir / "workpaper.xlsx").exists()

    # status now finalized
    info = runner.invoke(cli_app, ["status", config.run_id,
                                   "--runs-dir", str(tmp_path / "runs")])
    assert "finalized" in info.output


def test_finalize_cli_blocks_when_gates_fail(tmp_path):
    ctx, con, config = setup_run(tmp_path, run_id="BLOCK_Q2")
    # no decisions at all -> gate1 must fail
    store = RunStore(ctx.runstore_path)
    store.close()
    con.close()

    runner = CliRunner()
    result = runner.invoke(cli_app, ["finalize", "BLOCK_Q2",
                                     "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 1
    assert "FAIL" in result.output
