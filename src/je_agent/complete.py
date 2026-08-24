"""Auto-finalize — one call takes a run from whatever stage it's at to a complete
report. The agent's job: fill any missing phase, document limitations, run gates,
and emit all deliverables. No human step required beyond recording decisions.

Usage: complete_run(run_dir) — used by the API /finalize endpoint so a single
click produces cover -> findings -> triage -> review -> narrative -> report.pdf.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

from .config import load_config
from .document import (
    active_limitations,
    build_facts_block,
    build_workpaper,
    finalize_gates,
)
from .llm.provider import OpenAICompatibleProvider
from .narrate import run_narrate
from .report import export_pdf
from .run_context import RunContext
from .store import RunStore
from .triage import run_triage
from .universe import select_universe
from .workpaper import write_workpaper


def _provider(config):
    """Build the run's provider from config + env key (never stored)."""
    key = os.environ.get("JEAGENT_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return OpenAICompatibleProvider(
        base_url=config.provider.base_url,
        model=config.provider.model,
        api_key=key,
    )


def complete_run(run_dir: Path, accept_limitations: bool = True) -> dict:
    """Advance a run to finalized + report.pdf, filling missing LLM stages.

    If decisions are missing for universe entries, those are reported (gates will
    fail) — this function does NOT invent audit judgments. Everything else that
    can be produced is produced.
    """
    ctx = RunContext(run_dir)
    config = load_config(ctx.dir / "config.yaml")
    store = RunStore(ctx.runstore_path)
    con = duckdb.connect(str(ctx.duckdb_path))

    try:
        universe = select_universe(con, config)
        report = {}

        # 1) run_triage if not already present
        triage_path = ctx.llm_dir / "triage_report.json"
        if not triage_path.exists():
            provider = _provider(config)
            t = run_triage(con, config, provider, universe, store, config.run_id,
                           save_to=triage_path)
            store.record_event(config.run_id, "triage",
                               f"auto-triaged {t.universe_covered}/{universe.selected}")
            report["triage"] = {"covered": t.universe_covered,
                                "packs": len(t.pack_ids)}
        else:
            report["triage"] = {"covered": "already present"}

        # 2) run_narrate if not already present (feeds facts + triage summary)
        narrative_path = ctx.llm_dir / "narrative.json"
        if not narrative_path.exists():
            triage_summary = ""
            if triage_path.exists():
                triage_summary = triage_path.read_text(encoding="utf-8")[:1500]
            provider = _provider(config)
            res = run_narrate(con, config, provider, universe, store, config.run_id,
                              triage_summary=triage_summary, save_to=narrative_path)
            store.record_event(config.run_id, "narrate", "auto-narrated")
            report["narrate"] = "generated"
        else:
            report["narrate"] = "already present"

        # 3) facts + limitation acceptance + gates
        facts = build_facts_block(con, config, universe, None, store)
        accepted = set(active_limitations(con, config, universe)) if accept_limitations else set()
        gates = finalize_gates(con, config, universe, None, facts, store,
                               accepted_limitations=accepted, procedure_failures={})

        # load narrative artifact for citation gate / workpaper
        from .schemas import Narrative

        narrative = None
        if narrative_path.exists():
            narrative = Narrative.model_validate_json(narrative_path.read_text(encoding="utf-8"))
            gates = finalize_gates(con, config, universe, narrative, facts, store,
                                   accepted_limitations=accepted, procedure_failures={})

        report["gates"] = {
            "g1_review": gates.gate1_review_complete,
            "g2_procedures": gates.gate2_procedures_complete,
            "g3_citations": gates.gate3_citations_valid,
            "g4_limitations": gates.gate4_limitations_accepted,
            "problems": gates.problems,
            "all_passed": gates.all_passed,
        }

        if not gates.all_passed:
            # still produce partial report so feedback is visual
            store.close()
            con.close()
            return report

        # 4) workpaper + PDF report
        wp = build_workpaper(ctx, config, facts, narrative, store,
                             limitations_accepted=accepted)
        write_workpaper(ctx.artifacts_dir / "workpaper.xlsx", wp)
        # release DB handles BEFORE export_pdf: build_report reopens workspace.duckdb
        # read-only, which DuckDB refuses while the write config is still open.
        con.close()
        store.close()
        pdf = export_pdf(ctx.dir)
        store = RunStore(ctx.runstore_path)  # reopen only to stamp final status
        store.set_status(config.run_id, "finalized", "DOCUMENT")
        store.record_event(config.run_id, "finalize", f"auto-finalized: {pdf.name}")
        report["status"] = "finalized"
        report["artifacts"] = ["workpaper.xlsx", pdf.name]
        store.close()
        return report
    except Exception:
        store.close()
        con.close()
        raise
