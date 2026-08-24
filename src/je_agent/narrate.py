"""NARRATE phase (§4.1 job 3) — keyed facts block -> cited prose via the gated loop.

The model receives ONLY the facts block + triage summary (never raw data) and must
end with submit_narrative whose [fact:key] citations resolve (C1). One repair
retry, then loud failure — same discipline as planning/triage.
"""

from __future__ import annotations

import duckdb

from .config import EngagementConfig
from .document import REQUIRED_FACT_KEYS, validate_citations
from .hashing import canonical_json
from .llm.provider import LLMProvider
from .phase_runner import PhaseResult, run_phase
from .schemas import Narrative
from .store import RunStore
from .universe import UniverseSelection

NARRATE_SYSTEM = """You are an audit workpaper narrator for journal-entry testing (ISA 240 / AS 2401).

1. You never compute. Every number you state MUST appear as a [fact:key] citation
   resolving to the facts block provided. Never write numerals from memory.
2. You end the phase by calling submit_narrative; anything outside that call is discarded.
3. Cite EVERY key listed under required_facts at least once across sections.
4. Professional, factual tone. Describe what was tested, what flagged, what the
   human decided, and what limitations apply. Do not speculate beyond the facts.
5. If a fact you need is missing, note its absence instead of inventing content."""


def _tool_spec(facts: dict[str, str]) -> list[dict]:
    keys = sorted(facts)
    return [{
        "name": "submit_narrative",
        "description": ("Submit the final workpaper narrative. Every claim carries "
                        "[fact:key] citations that resolve in the provided facts block."),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "sections": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["heading", "text"],
                    },
                },
                "cited_fact_keys": {
                    "type": "array",
                    "items": {"type": "string", "enum": keys},
                },
            },
            "required": ["title", "sections", "cited_fact_keys"],
        },
    }]


def _make_validator(facts: dict[str, str]):
    def validate(narrative: Narrative) -> list[str]:
        return validate_citations(narrative, facts)
    return validate


def run_narrate(con: duckdb.DuckDBPyConnection,
                config: EngagementConfig,
                provider: LLMProvider,
                universe: UniverseSelection,
                store: RunStore,
                run_id: str,
                triage_summary: str = "",
                save_to=None) -> PhaseResult:
    from .document import build_facts_block

    facts = build_facts_block(con, config, universe, None, store)

    # findings-voice: hand the model the engagement's risk-rated 5C findings so
    # the prose matches the report's analytical depth (never contradicts it).
    findings_text = ""
    try:
        from .report import _executive_assessment
        from .review import effective_decisions
        from .stats import run_benford as _ben

        exec_rows = store.con.execute("""
            SELECT tool, CAST(json_extract(result_json,'$.flagged') AS INT)
            FROM tool_calls WHERE phase='EXECUTE' AND outcome='ok'
              AND result_json IS NOT NULL ORDER BY seq""").fetchall()
        rule_counts = dict(exec_rows)
        flagged_docs = con.execute(
            "SELECT count(DISTINCT entry_ref) FROM xref_ranked").fetchone()[0]
        population = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
        bluf, findings = _executive_assessment(
            config, population, flagged_docs, universe,
            effective_decisions(store, run_id), rule_counts,
            None, _ben(con, run_id), True, config.materiality.currency)
        blocks = [f"BLUF: {bluf}"]
        for f in findings:
            blocks.append(
                f"[{f['severity'].upper()}] {f['title']} — Condition: {f['condition']} "
                f"Corrective action: {f['corrective']}")
        findings_text = "\n".join(blocks)
    except Exception:
        findings_text = ""

    fact_lines = "\n".join(f"- {k}: {v}" for k, v in sorted(facts.items()))
    brief = (
        f"Facts block for run {run_id} (period end {config.period_end}):\n"
        f"{fact_lines}\n\n"
        f"Triage summary (context only): {triage_summary[:1500]}\n\n"
        + (f"Engagement findings (authoritative — your narrative MUST be consistent "
           f"with these, may reference them by name, but numbers still require "
           f"[fact:key] citations):\n{findings_text}\n\n" if findings_text else "")
        + f"Required facts to cite: {', '.join(REQUIRED_FACT_KEYS)}\n\n"
        "CITATION CONTRACT: EVERY section you write must contain at least one "
        "[fact:key] citation inline (e.g. \"We tested [fact:population_lines] lines\"). "
        "A section without any citation will be rejected. All citations must resolve "
        "in the facts block above.\n\n"
        "Draft the workpaper narrative now: 4-5 sections (Scope & approach, "
        "Flagging results, Findings & observations, Review outcomes, "
        "Limitations & follow-ups) written in the voice of a senior auditor — "
        "specific, conclusions-first, no filler. End by calling submit_narrative."
    )
    result: PhaseResult = run_phase(
        phase_name="DOCUMENT/NARRATE",
        provider=provider,
        system_prompt=NARRATE_SYSTEM,
        user_brief=brief,
        tools_spec=_tool_spec(facts),
        submit_tool="submit_narrative",
        artifact_model=Narrative,
        referential_validator=_make_validator(facts),
        store=store, run_id=run_id,
        context_hash=canonical_json(facts)[:16],
    )
    if save_to is not None:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_text(result.artifact.model_dump_json(indent=2), encoding="utf-8")
    return result
