"""flag_entry_splitting — step 5 (v1.2 V3): salami tactics, just-below-threshold groups.

Precision guards (golden-fixture driven): only MANUAL lines participate (system
volume to busy accounts is not salami slicing), and "just below" means
amount >= split_just_below_ratio * split_threshold — clustering near the threshold
is the signal, mere sub-threshold volume is not. Buckets are fixed windows of
`split_window_days` from a fixed epoch: deterministic and explainable.
"""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_entry_splitting"
_EPOCH = "2000-01-01"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params
    lo = p.split_threshold * p.split_just_below_ratio

    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        WITH buckets AS (
            SELECT *,
                   date_diff('day', DATE '{_EPOCH}', posting_date) // ? AS bucket_id
            FROM journal_lines
            WHERE is_manual
              AND ABS(amount) >= ?      -- just-below lower bound (ratio)
              AND ABS(amount) < ?       -- strictly below threshold
        ),
        qualified AS (
            SELECT account, bucket_id
            FROM buckets
            GROUP BY account, bucket_id
            HAVING COUNT(*) >= ? AND SUM(ABS(amount)) > ?
        )
        SELECT b.entry_ref,
               b.line_no,
               b.username,
               b.amount,
               b.posting_date,
               'split pattern: ' || CAST(q.bucket_id AS VARCHAR) ||
                 ' cluster (' || q.account || ')' AS flag_reason
        FROM buckets b
        JOIN qualified q USING (account, bucket_id)
    """, [p.split_window_days, lo, p.split_threshold, p.split_min_count, p.split_threshold])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="entry_splitting",
        flagged=flagged,
        output_table=TABLE,
        notes=f"manual lines in [{lo:.2f}, {p.split_threshold}) buckets of "
              f"{p.split_window_days}d; >= {p.split_min_count} to one account, sum > {p.split_threshold}",
    )
