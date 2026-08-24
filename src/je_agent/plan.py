"""Constant RiskPlan producer — the Phase 1 seam (§2.3).

"All rules, default params" as a deterministic plan. Phase 2 swaps an LLM planner
in behind this same interface; every downstream consumer is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import CANONICAL_RULE_ORDER


@dataclass
class RuleSelection:
    rule: str
    params: dict
    rationale: str


@dataclass
class RiskPlan:
    selections: list[RuleSelection]
    statistical: list[str] = field(default_factory=list)
    focus_areas: list[str] = field(default_factory=list)
    plan_note: str = ""
    producer: str = "constant"      # 'constant' now; 'llm' from Phase 2


def constant_risk_plan(risk_context=None) -> RiskPlan:
    """Every gating rule at configured defaults, in canonical order."""
    factors = getattr(risk_context, "fraud_risk_factors", None) or ["none"]
    selections = [
        RuleSelection(rule=name, params={}, rationale="phase-1 constant plan: full coverage")
        for name in CANONICAL_RULE_ORDER
        if name != "high_risk_system_pairs"   # informational screen still executes, below
    ]
    # informational screens ride along but never gate
    selections.append(RuleSelection(
        rule="high_risk_system_pairs", params={},
        rationale="informational blind-spot screen (W6); never gates"))
    return RiskPlan(
        selections=selections,
        focus_areas=factors[:3],
        plan_note="Deterministic Phase 1 plan: all rules, default parameters.",
    )
