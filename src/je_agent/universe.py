"""Review-universe selection (DESIGN §8 TRIAGE; A2, W1, X2, Y8).

Universe = flagged entries above performance materiality (+ representative sample,
P2-M6), capped by review.max_universe_size with overflow_policy semantics. Without
usable fx coverage the selection falls back to CURRENCY-STRATIFIED top-N per
currency — never a global mixed-currency ranking — globally capped; excluded minor
currencies are documented with count, volume share, and largest single entry;
force_include_currencies / minimum_entries_per_currency override pure volume
ranking. Selection basis is recorded per entry ('targeted' | 'representative').
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from .config import EngagementConfig


class UniverseOverflow(RuntimeError):
    """W1: overflow under policy 'pause' — requires a documented auditor decision."""

    def __init__(self, total: int, cap: int):
        super().__init__(
            f"review universe {total} exceeds max_universe_size {cap} "
            "(policy=pause): stratify, raise materiality, or accept a scoped limitation")
        self.total = total
        self.cap = cap


@dataclass
class ExcludedCurrency:
    currency: str
    entries: int
    volume_share: float
    largest_entry_abs: float


@dataclass
class UniverseSelection:
    entries: list[dict]
    total_flagged: int
    selected: int
    fallback_used: bool = False
    capped_by_rank: bool = False          # document_limitation / stratify path
    overflow_paused: bool = False
    excluded_currencies: list[ExcludedCurrency] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _fx_convertible(config: EngagementConfig, currencies: set[str]) -> bool:
    rates = {k.upper(): v for k, v in config.fx_rates.items()}
    base = config.materiality.currency.upper()
    return all(c == base or c in rates for c in currencies)


def select_universe(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> UniverseSelection:
    rev = config.review
    pm = config.materiality.performance
    base_ccy = config.materiality.currency.upper()
    rates = {k.upper(): v for k, v in config.fx_rates.items()}

    rows = con.execute("""
        SELECT DISTINCT x.entry_ref,
               MAX(x.rules_hit)      AS rules_hit,
               MAX(x.abs_amount)     AS abs_amount,
               MIN(j.currency)       AS currency
        FROM xref_ranked x
        JOIN journal_lines j USING (entry_ref)
        GROUP BY x.entry_ref
        ORDER BY rules_hit DESC, abs_amount DESC
    """).fetchall()

    total = len(rows)

    # ---- single-currency or fully-covered-by-fx path -------------------------
    currencies = {r[3] or base_ccy for r in rows}

    def base_amount(abs_amt: float, ccy: str | None) -> float:
        c = (ccy or base_ccy).upper()
        return float(abs_amt) * rates.get(c, 1.0) if c != base_ccy else float(abs_amt)

    if _fx_convertible(config, currencies):
        above = [
            {"entry_ref": r[0], "rules_hit": r[1], "abs_amount": float(r[2]),
             "currency": r[3], "selection_basis": "targeted"}
            for r in rows if base_amount(r[2], r[3]) >= pm
        ]
        if len(above) <= rev.max_universe_size:
            return UniverseSelection(entries=above, total_flagged=total,
                                     selected=len(above))
        # still capped: rank-cut below
        return _cap_by_rank(rows_converted=[(a["entry_ref"], a["rules_hit"], a["abs_amount"],
                                             a["currency"], base_amount(a["abs_amount"], a["currency"]))
                                            for a in above],
                            config=config, total=total)

    # ---- X2/Y8 currency-stratified fallback ---------------------------------
    per_ccy: dict[str, list[tuple]] = {}
    vol: dict[str, float] = {}
    for ref, hit, amt, ccy in rows:
        c = (ccy or base_ccy).upper()
        per_ccy.setdefault(c, []).append((ref, hit, float(amt)))
        vol[c] = vol.get(c, 0.0) + float(amt)
    total_vol = sum(vol.values()) or 1.0

    forced = {c.upper() for c in rev.force_include_currencies}
    ranking = sorted(vol, key=lambda c: vol[c], reverse=True)
    for c in forced:                                   # Y8: forced currencies first
        if c in ranking:
            ranking.remove(c)
        ranking.insert(0, c)

    remaining_cap = rev.max_universe_size
    chosen: list[dict] = []
    excluded: list[ExcludedCurrency] = []

    # floors first (Y8): every kept currency gets its minimum before allocation
    allocations: dict[str, int] = {}
    for c in ranking:
        floor = min(rev.minimum_entries_per_currency, len(per_ccy[c])) \
            if rev.minimum_entries_per_currency else 0
        take = min(floor, remaining_cap)
        allocations[c] = take
        remaining_cap -= take

    # then volume-ranked top-N with what remains
    for c in ranking:
        room = rev.fallback_top_n_per_currency
        want = min(room, len(per_ccy[c]))
        extra = max(0, min(want - allocations[c], remaining_cap))
        allocations[c] += extra
        remaining_cap -= extra

    for c in ranking:
        c_rows = sorted(per_ccy[c], key=lambda t: t[2], reverse=True)
        take = allocations.get(c, 0)
        for ref, hit, amt in c_rows[:take]:
            chosen.append({"entry_ref": ref, "rules_hit": hit, "abs_amount": amt,
                           "currency": c, "selection_basis": "targeted"})
        if take < len(c_rows):
            dropped = c_rows[take:]
            excluded.append(ExcludedCurrency(
                currency=c, entries=len(dropped),
                volume_share=vol[c] / total_vol,
                largest_entry_abs=max(a for _, _, a in dropped)))

    notes = ["no usable fx coverage for all currencies; currency-stratified "
             "top-N per currency applied (X2), globally capped"]
    if forced & set(ranking[:len(forced)]):
        notes.append(f"force_include_currencies honored: {sorted(forced)}")
    sel = UniverseSelection(entries=chosen, total_flagged=total, selected=len(chosen),
                            fallback_used=True, excluded_currencies=excluded, notes=notes)
    return sel


def _cap_by_rank(rows_converted: list[tuple], config: EngagementConfig,
                 total: int) -> UniverseSelection:
    rev = config.review
    cap = rev.max_universe_size
    ordered = sorted(rows_converted, key=lambda t: (-t[1], -t[4]))  # rules_hit desc, base amt desc
    if rev.overflow_policy == "pause":
        raise UniverseOverflow(total, cap)
    picked = ordered[:cap]
    entries = [{"entry_ref": r[0], "rules_hit": r[1], "abs_amount": float(r[2]),
                "currency": r[3], "selection_basis": "targeted"} for r in picked]
    return UniverseSelection(
        entries=entries, total_flagged=total, selected=len(entries),
        capped_by_rank=True,
        notes=[f"overflow policy '{rev.overflow_policy}': capped to {cap} of {total} "
               f"by (rules_hit, base-amount) rank; documented limitation required"])
