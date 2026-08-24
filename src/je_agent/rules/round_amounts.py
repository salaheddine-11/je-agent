"""flag_round_amounts — step 3: amounts divisible by `multiple` above a floor (§5.6)."""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_round_amounts"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT entry_ref,
               line_no,
               username,
               amount,
               'round amount (' || CAST(CAST(ABS(amount) AS BIGINT) AS VARCHAR) || ')' AS flag_reason
        FROM journal_lines
        WHERE ABS(amount) >= ?
          AND MOD(CAST(ABS(amount) AS BIGINT), CAST(? AS BIGINT)) = 0
    """, [p.round_number_min_amount, p.round_number_multiple])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="round_amounts",
        flagged=flagged,
        output_table=TABLE,
        notes=f"abs(amount) ≥ {p.round_number_min_amount} divisible by {p.round_number_multiple}",
    )
