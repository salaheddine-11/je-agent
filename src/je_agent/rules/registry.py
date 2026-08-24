"""Rule registry + executor (DESIGN §5.3–§5.5, v1.6 Z2 canonical order)."""

from __future__ import annotations

import duckdb

from ..config import CANONICAL_RULE_ORDER, EngagementConfig
from .base import RuleError, RuleResult

# canonical order (Z2): the executor re-sorts any plan into this sequence
_REGISTRY = {
    "manual_entries": ("je_agent.rules.manual_entries", "flags_manual_entries"),
    "period_end": ("je_agent.rules.period_end", "flags_period_end"),
    "round_amounts": ("je_agent.rules.round_amounts", "flags_round_amounts"),
    "date_divergence": ("je_agent.rules.date_divergence", "flags_date_divergence"),
    "entry_splitting": ("je_agent.rules.entry_splitting", "flags_entry_splitting"),
    "balance_check": ("je_agent.rules.balance_check", "flags_balance_check"),
    "unusual_users": ("je_agent.rules.unusual_users", "flags_unusual_users"),
    "unusual_pairs": ("je_agent.rules.unusual_pairs", "flags_unusual_pairs"),
    "reversals": ("je_agent.rules.reversals", "flags_reversals"),
    "high_risk_system_pairs": (
        "je_agent.rules.high_risk_system_pairs",
        "flags_high_risk_system_pairs",
    ),
}


def registry_order() -> list[str]:
    return list(CANONICAL_RULE_ORDER)


def execute_rules(
    con: duckdb.DuckDBPyConnection,
    config: EngagementConfig,
    selected: list[str] | None = None,
) -> list[RuleResult]:
    """Execute rules in canonical order regardless of `selected` order (Z2).

    Per-rule failures are caught and returned as RuleError results; the batch
    continues (§5.4 plan-is-script; A3 procedure gaps handled upstream).
    """
    import importlib

    wanted = list(selected) if selected else registry_order()
    # re-sort into canonical order; unknown names rejected
    known = set(_REGISTRY)
    unknown = [r for r in wanted if r not in known]
    if unknown:
        raise ValueError(f"unknown rule(s): {sorted(unknown)}")
    ordered = sorted(set(wanted), key=registry_order().index)

    results: list[RuleResult | RuleError] = []
    for name in ordered:
        module_name, _table = _REGISTRY[name]
        try:
            mod = importlib.import_module(module_name)
            results.append(mod.run(con, config))
        except Exception as e:  # noqa: BLE001 — per-rule failure, batch continues
            results.append(
                RuleError(rule=name, code="internal", message=str(e))
            )
    return results
