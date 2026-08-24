"""flag_reversals — step 9: near-negation shortly after period end (§5.6, v1.6 Z1).

Matches an in-period entry to a near-exact negation posted within `match_days`
after period end. Z1: when the extract lacks post-close coverage, the ingest DQ
profile warns and this rule's notes state the truncated observation window.
"""

from __future__ import annotations

import datetime as _dt

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_reversals"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params
    pe = _dt.date.fromisoformat(config.period_end)
    window_end = pe + _dt.timedelta(days=p.reversal_match_days)
    tol = p.reversal_amount_tolerance

    # Original: in-period line. Reversal: post-period-end line with amount ≈ -original.
    # Match on same account + same user (a true reversal is same-account by nature).
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT o.entry_ref,
               o.line_no,
               o.username,
               o.amount,
               'reversed ' || date_diff('day', CAST(? AS DATE), r.posting_date) ||
                 ' days after period end by ' || r.username AS flag_reason
        FROM journal_lines o
        JOIN journal_lines r
          ON r.account = o.account
         AND r.username = o.username
         AND r.posting_date > CAST(? AS DATE)
         AND r.posting_date <= CAST(? AS DATE)
         AND ABS(r.amount + o.amount) <= ?
        WHERE o.posting_date <= CAST(? AS DATE)
    """, [pe, pe, window_end, tol, pe])

    # The reversal side itself is also evidence — record it too (dedup by pair).
    con.execute(f"""
        INSERT INTO {TABLE}
        SELECT r.entry_ref,
               r.line_no,
               r.username,
               r.amount,
               'reversal of in-period entry' AS flag_reason
        FROM journal_lines r
        WHERE EXISTS (
            SELECT 1 FROM journal_lines o
            WHERE o.account = r.account
              AND o.username = r.username
              AND o.posting_date <= CAST(? AS DATE)
              AND r.posting_date > CAST(? AS DATE)
              AND r.posting_date <= CAST(? AS DATE)
              AND ABS(r.amount + o.amount) <= ?
        )
          AND NOT EXISTS (
            SELECT 1 FROM {TABLE} t WHERE t.entry_ref = r.entry_ref AND t.line_no = r.line_no
        )
    """, [pe, pe, window_end, tol])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="reversals",
        flagged=flagged,
        output_table=TABLE,
        notes=f"observation window: period end {pe} + {p.reversal_match_days}d "
              f"(through {window_end}); truncated coverage raises dq_no_post_close_coverage at ingest",
    )
