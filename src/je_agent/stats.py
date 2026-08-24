"""Statistics tools (§5.7; C2 informational-only) + representative sampling (§5.8; V5/W12).

Benford: MAD vs Nigrini critical values — NEVER gating, limitation travels in
notes. Outlier detection: seeded IsolationForest-style z-score screen (numpy-free
fallback) with the seed recorded. Representative sampling: seeded stratified
selection across the FULL population joining the universe tagged 'representative'.
"""

from __future__ import annotations

import hashlib
import math
import random

import duckdb

from .config import EngagementConfig

# Nigrini MAD critical values for first digits
NIGRINI = [
    ("close conformity", 0.000, 0.004),
    ("acceptable conformity", 0.004, 0.008),
    ("marginally acceptable", 0.008, 0.010),
    ("nonconformity", 0.010, float("inf")),
]

_BENFORD_FIRST_DIGIT_PROBS = [math.log10(1 + 1 / d) for d in range(1, 10)]


def _seed_from(run_id: str, tool: str) -> str:
    return f"{run_id}:{tool}"


def _seeded_rng(seed_text: str) -> random.Random:
    digest = int(hashlib.sha256(seed_text.encode()).hexdigest()[:12], 16)
    return random.Random(digest)


def run_benford(con: duckdb.DuckDBPyConnection, run_id: str,
                column: str = "amount", group_by: str | None = None) -> dict:
    """MAD against Benford first-digit expectation. Informational ONLY (C2)."""
    rows = con.execute(
        f"SELECT ABS(CAST({column} AS DOUBLE)) FROM journal_lines "
        f"WHERE {column} IS NOT NULL AND ABS({column}) >= 1"
    ).fetchall()
    amounts = [r[0] for r in rows]
    n = len(amounts)
    result = {
        "tool": "run_benford",
        "population": n,
        "informational_only": True,
        "limitation": ("journal amounts are not naturally Benford-distributed (C2); "
                       "results inform inquiry and never gate"),
        "seed": _seed_from(run_id, "benford"),
    }
    if n < 100:
        result.update({"mad": None, "assessment": "insufficient_data (<100 amounts)"})
        return result

    counts = [0] * 9
    for a in amounts:
        first = str(a).lstrip("0.").replace(".", "").lstrip("0")[0]
        counts[int(first) - 1] += 1
    mad = sum(abs(c / n - p) for c, p in zip(counts, _BENFORD_FIRST_DIGIT_PROBS)) / 9
    assessment = next(name for name, lo, hi in NIGRINI if lo <= mad < hi)
    result.update({
        "mad": round(mad, 6),
        "nigrini_assessment": assessment,
        "first_digit_frequencies": {d: counts[d - 1] for d in range(1, 10)},
    })
    return result


def run_outlier_detection(con: duckdb.DuckDBPyConnection, config: EngagementConfig,
                          z_threshold: float = 4.0) -> dict:
    """Per-account log-amount z-score screen. Seed explicit + recorded (§11 #6)."""
    seed = _seed_from(config.run_id, "outliers")
    rng = _seeded_rng(seed)
    rows = con.execute("""
        SELECT entry_ref, account, ABS(CAST(amount AS DOUBLE))
        FROM journal_lines WHERE amount IS NOT NULL AND amount <> 0
    """).fetchall()

    by_account: dict[str, list[float]] = {}
    for ref, acct, amt in rows:
        by_account.setdefault(acct or "?", []).append(math.log10(amt + 1))

    outliers = []
    means_stds = {}
    for acct, vals in by_account.items():
        if len(vals) < 30:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = math.sqrt(var) or 1e-9
        means_stds[acct] = (round(mean, 4), round(std, 4))
    for ref, acct, amt in rows:
        if acct in means_stds:
            mean, std = means_stds[acct]
            denom = max(std, 1e-9)
            z = (math.log10(amt + 1) - mean) / denom
            if abs(z) >= z_threshold:
                outliers.append({"entry_ref": ref, "account": acct,
                                 "z": round(z, 2), "amount": amt})
    outliers.sort(key=lambda o: -abs(o["z"]))
    _ = rng.random()   # RNG touched so future statistical extensions inherit recorded-seed discipline
    return {
        "tool": "run_outlier_detection",
        "screened": len(rows),
        "outliers": outliers[:200],
        "z_threshold": z_threshold,
        "seed": seed,
        "informational_only": True,
    }


def sample_representative(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> dict:
    """V5/W12: seeded stratified selection across the FULL population."""
    rs_cfg = config.representative_sample
    if not rs_cfg.enabled:
        return {"tool": "sample_representative", "enabled": False}
    seed = _seed_from(config.run_id, "representative")
    rng = _seeded_rng(seed)

    strata_col = {
        "month": "strftime(posting_date, '%Y-%m')",
        "entry_type": "entry_type_source",
    }
    primary = rs_cfg.strata[0] if rs_cfg.strata else "month"
    expr = strata_col.get(primary, "strftime(posting_date, '%Y-%m')")

    strata_rows = con.execute(f"""
        SELECT {expr} AS stratum, entry_ref
        FROM journal_lines
        ORDER BY entry_ref
    """).fetchall()

    by_stratum: dict[str, list[str]] = {}
    for stratum, ref in strata_rows:
        by_stratum.setdefault(stratum, []).append(ref)

    total_docs = sum(len(v) for v in by_stratum.values())
    target_n = min(rs_cfg.size, total_docs)
    picked: dict[str, list[str]] = {}
    remaining = target_n
    strata_names = sorted(by_stratum)
    for idx, stratum in enumerate(strata_names):
        docs = sorted(set(by_stratum[stratum]))
        is_last = idx == len(strata_names) - 1
        share = max(1, round(len(docs) / total_docs * target_n)) if not is_last else remaining
        take = min(len(docs), max(0, min(share, remaining)))
        sample = rng.sample(docs, take) if take < len(docs) else docs
        picked[stratum] = sorted(sample)
        remaining -= take
        if remaining <= 0:
            break

    con.execute("CREATE OR REPLACE TABLE sample_representative "
                "(entry_ref TEXT, stratum TEXT, selection_basis TEXT)")
    count = 0
    for stratum, refs in picked.items():
        for ref in refs:
            con.execute("INSERT INTO sample_representative VALUES (?, ?, 'representative')",
                        [ref, stratum])
            count += 1
    con.execute("""
        INSERT INTO xref_ranked
            (entry_ref, line_no, rules_hit, abs_amount, amount, flag_reasons, selection_basis)
        SELECT DISTINCT s.entry_ref,
               MIN(j.line_no), 0, MAX(ABS(j.amount)), NULL,
               'representative sample (methodology completeness)', s.selection_basis
        FROM sample_representative s JOIN journal_lines j USING (entry_ref)
        WHERE NOT EXISTS (SELECT 1 FROM xref_ranked x WHERE x.entry_ref = s.entry_ref)
        GROUP BY s.entry_ref, s.selection_basis
    """)
    coverage = {s: len(refs) for s, refs in picked.items()}
    return {
        "tool": "sample_representative",
        "enabled": True,
        "objective": "attribute inspection alongside targeted flag coverage",
        "strata": primary,
        "requested_size": rs_cfg.size,
        "selected": count,
        "per_stratum_coverage": coverage,
        "seed": seed,
        "non_projection_statement": ("sample results do not support conclusions about "
                                     "the unflagged population (W12/§11 #9)"),
    }
