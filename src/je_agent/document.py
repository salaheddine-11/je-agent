"""DOCUMENT stage (DESIGN §8; A3, C1, C4, W11, Y3) — finalize gates 1-4 + workpaper.

Facts block is keyed structured data; the narrative must cite [fact:key] tokens
that RESOLVE in the block; the validator checks citations, never prose numerals.
Finalize requires ALL FOUR gates:
  1. review completeness   — every universe entry has an effective decision
  2. procedure completeness— every planned rule ok or a logged procedure gap
  3. narrative citations   — all cited keys resolve; required facts are cited
  4. limitation acceptance — every active limitation has a logged acceptance
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb

from .config import EngagementConfig
from .hashing import canonical_json
from .review import effective_decisions, verify_all_chains
from .schemas import Narrative, TriageReport
from .store import RunStore
from .universe import UniverseSelection

FACT_KEY_RE = re.compile(r"\[fact:([a-z0-9_]+)\]")

# facts that gate 3 REQUIRES to be cited somewhere in the narrative
REQUIRED_FACT_KEYS = [
    "population_lines",
    "flagged_documents",
    "universe_size",
    "decisions_inspect",
    "decisions_accept",
    "decisions_override",
]

# §11 mandatory scope & limitations (static core + dynamic additions)
BASE_LIMITATIONS = [
    "Vouching is external: entries marked 'inspect' leave this tool for substantive "
    "testing against supporting documentation; this workpaper lists them, it does not vouch them.",
    "Benford analysis is informational: journal amount populations are not naturally "
    "Benford-distributed; results inform inquiry, never conclude.",
    "System-entry account pairs are not screened: unusual_pairs defines its baseline from "
    "system entries of the current period, excluding previously flagged documents.",
    "Reviewer identity is declared, not authenticated, until SSO (reviewer_source distinguishes); "
    "decision rows are hash-chained so tampering is detectable, but identity is not yet non-repudiable.",
    "Statistical outlier results are seeded and recorded; seeds live in the run store.",
    "LLM outputs are documented, not deterministic — the reproducibility guarantee covers the "
    "deterministic path; the judgment path is fully logged instead.",
    "Triage follow-ups are recorded, not executed — acting on one is a deliberate new run.",
    "The representative sample supports targeted coverage, not statistical projection.",
    "LLM-facing free text is sanitized, not guaranteed safe: descriptions are delimited untrusted "
    "data and scanned for injection patterns; prompt-level defense is a mitigation, and the "
    "structural backstop is schema-constrained advisory output behind human review.",
    "PII scrubbing is pattern-based: regex classes and configured redaction terms remove structured "
    "identifiers from LLM-bound text but cannot catch all sensitive prose.",
]


@dataclass
class GateReport:
    gate1_review_complete: bool
    gate2_procedures_complete: bool
    gate3_citations_valid: bool
    gate4_limitations_accepted: bool
    problems: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all([self.gate1_review_complete, self.gate2_procedures_complete,
                    self.gate3_citations_valid, self.gate4_limitations_accepted])


# ---------------------------------------------------------------------------
# facts block (keyed structured data — the ONLY numbers the LLM may reference)
# ---------------------------------------------------------------------------


def build_facts_block(con: duckdb.DuckDBPyConnection, config: EngagementConfig,
                      universe: UniverseSelection,
                      triage: TriageReport | None,
                      store: RunStore) -> dict[str, str]:
    eff = effective_decisions(store, config.run_id)
    counts = {"inspect": 0, "accept": 0, "override": 0}
    for d in eff.values():
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1

    population = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
    flagged = con.execute("SELECT count(DISTINCT entry_ref) FROM xref_ranked").fetchone()[0]
    rules = {}
    try:
        rules = dict(store.con.execute("""
            SELECT tool, CAST(json_extract(result_json, '$.flagged') AS INTEGER)
            FROM tool_calls WHERE phase='EXECUTE' AND outcome='ok'
            GROUP BY tool
        """).fetchall())
    except Exception:
        pass   # store without EXECUTE records yet -> rule facts simply absent

    facts = {
        "run_id": config.run_id,
        "period_end": config.period_end,
        "population_lines": str(population),
        "flagged_documents": str(flagged),
        "universe_size": str(universe.selected),
        "total_flagged_before_cap": str(universe.total_flagged),
        "selection_basis": "targeted" if not universe.fallback_used else "currency-stratified fallback",
        "decisions_inspect": str(counts.get("inspect", 0)),
        "decisions_accept": str(counts.get("accept", 0)),
        "decisions_override": str(counts.get("override", 0)),
    }
    for rule, flagged_n in sorted(rules.items()):
        facts[f"rule_{rule}"] = str(flagged_n)
    if triage is not None:
        facts["followups_recorded"] = str(len(triage.suggested_followups))
        facts["consistency_warnings"] = str(len(triage.consistency_warnings))
    return facts


# ---------------------------------------------------------------------------
# citation validation (C1): check citations resolve, NEVER parse prose numerals
# ---------------------------------------------------------------------------


def validate_citations(narrative: Narrative, facts: dict[str, str]) -> list[str]:
    problems = []
    text = "\n".join(s.get("text", "") for s in narrative.sections)
    cited = set(FACT_KEY_RE.findall(text)) | set(narrative.cited_fact_keys)
    unknown = sorted(cited - set(facts))
    if unknown:
        problems.append(f"citations do not resolve in facts block: {unknown[:10]}")
    uncited_required = [k for k in REQUIRED_FACT_KEYS if k not in cited]
    if uncited_required:
        problems.append(f"required facts not cited: {uncited_required}")
    # sections must carry at least one citation each (prose anchored to data)
    for i, s in enumerate(narrative.sections):
        if not FACT_KEY_RE.search(s.get("text", "")):
            problems.append(f"section {i} ('{s.get('heading', '?')}') cites no [fact:key]")
            break
    return problems


# ---------------------------------------------------------------------------
# finalize gates 1-4
# ---------------------------------------------------------------------------


def finalize_gates(con: duckdb.DuckDBPyConnection, config: EngagementConfig,
                   universe: UniverseSelection,
                   narrative: Narrative | None,
                   narrative_facts: dict[str, str],
                   store: RunStore,
                   accepted_limitations: set[str],
                   procedure_failures: dict[str, str]) -> GateReport:
    problems: list[str] = []

    # gate 1: review completeness
    eff = effective_decisions(store, config.run_id)
    missing = [e["entry_ref"] for e in universe.entries if e["entry_ref"] not in eff]
    gate1 = not missing
    if missing:
        problems.append(f"gate1: {len(missing)} universe entries lack decisions "
                        f"(e.g. {missing[:5]})")

    # gate 2: procedure completeness (A3)
    failed = {r: msg for r, msg in procedure_failures.items()}
    uncovered = [r for r in failed if r not in accepted_limitations]
    gate2 = not uncovered
    if uncovered:
        problems.append(f"gate2: failed procedures without logged gap: {sorted(uncovered)}")

    # gate 3: narrative citation check (C1)
    gate3 = True
    if narrative is None:
        gate3 = False
        problems.append("gate3: no narrative artifact")
    else:
        cit_problems = validate_citations(narrative, narrative_facts)
        gate3 = not cit_problems
        problems.extend(f"gate3: {p}" for p in cit_problems)

    # gate 4: limitation acceptance — active limitations must be accepted (logged)
    active = active_limitations(con, config, universe)
    unaccepted = [lim for lim in active if lim not in accepted_limitations]
    gate4 = not unaccepted
    if unaccepted:
        problems.append(f"gate4: unaccepted limitations: {unaccepted[:5]}")

    return GateReport(gate1, gate2, gate3, gate4, problems)


def active_limitations(con: duckdb.DuckDBPyConnection, config: EngagementConfig,
                       universe: UniverseSelection) -> list[str]:
    """Dynamic limitation ids beyond the static base section."""
    lims = []
    if universe.fallback_used:
        lims.append("currency_stratified_fallback")
        for x in universe.excluded_currencies:
            lims.append(f"currency_excluded_{x.currency}")
    for w in _active_dq_critical(con):
        lims.append(f"dq_{w}")
    return lims


def _active_dq_critical(con: duckdb.DuckDBPyConnection) -> list[str]:
    try:
        rows = con.execute("""
            SELECT DISTINCT warning_id FROM dq_warnings_active WHERE severity='critical'
        """).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# workpaper assembly (xlsx): Scope&Lim, DQ appendix, AI Governance, Y3 lists
# ---------------------------------------------------------------------------


def build_workpaper(ctx, config: EngagementConfig, facts: dict[str, str],
                    narrative: Narrative | None, store: RunStore,
                    limitations_accepted: set[str]) -> dict:
    """Assemble the final workpaper payload (xlsx writer consumes this)."""
    chains = verify_all_chains(store, config.run_id)
    integrity = all(c.intact for c in chains.values())

    sections = []
    if narrative is not None:
        for s in narrative.sections:
            text = FACT_KEY_RE.sub(lambda m: f"{m.group(1)}={facts.get(m.group(1), '?')}",
                                   s.get("text", ""))
            sections.append({"heading": s.get("heading", ""), "text": text})

    return {
        "title": f"Journal Entry Testing Workpaper — {config.run_id}",
        "period_end": config.period_end,
        "facts": facts,
        "narrative_sections": sections,
        "scope_and_limitations": {
            "base": BASE_LIMITATIONS,
            "dynamic_accepted": sorted(limitations_accepted),
        },
        "dq_appendix": store.con.execute(
            "SELECT warning_id, scope, reason, reviewer FROM dq_acknowledgments "
            "WHERE run_id = ? ORDER BY id", [config.run_id]).fetchall(),
        "ai_governance": {
            "deterministic": ("ingest, rules, cross-ref, ranking, DQ profile, gates — all "
                              "deterministic Python/SQL under canonical order"),
            "llm_contribution": "risk planning (Phase 2+), triage concern ratings, narrative prose",
            "human_contribution": "universe overflow decision, every entry decision, "
                                  "DQ acknowledgments, injection dispositions, limitation acceptance",
            "chain_integrity_verified": integrity,
        },
    }


__all__ = [
    "GateReport", "REQUIRED_FACT_KEYS", "BASE_LIMITATIONS",
    "build_facts_block", "validate_citations", "finalize_gates",
    "active_limitations", "build_workpaper",
]

_ = canonical_json
