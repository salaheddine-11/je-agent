"""flag_period_end — step 2: manual entries near period end incl. post-close (§5.6)."""

from __future__ import annotations

import datetime as _dt

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_period_end"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params
    pe = _dt.date.fromisoformat(config.period_end)
    lo = pe - _dt.timedelta(days=p.period_end_window_days)
    hi = pe + _dt.timedelta(days=p.period_end_post_close_days)

    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT entry_ref,
               line_no,
               username,
               amount,
               posting_date,
               CASE WHEN posting_date > CAST(? AS DATE)
                    THEN 'manual entry posted post-close'
                    ELSE 'manual entry near period end' END AS flag_reason
        FROM journal_lines
        WHERE is_manual
          AND posting_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    """, [pe, lo, hi])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="period_end",
        flagged=flagged,
        output_table=TABLE,
        notes=f"window {lo} .. {hi}",
    )
