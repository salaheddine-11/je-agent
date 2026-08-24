"""flag_unusual_users — step 7: rare-manual users + configured high-risk users (§5.6)."""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_unusual_users"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params

    # Manual-entry frequency per user; "rare" = at most `rare_threshold` manual lines.
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        WITH manual_freq AS (
            SELECT username, COUNT(*) AS n_manual
            FROM journal_lines
            WHERE is_manual AND username IS NOT NULL
            GROUP BY username
        ),
        rare_users AS (
            SELECT username FROM manual_freq WHERE n_manual <= ?
        ),
        high_risk AS (
            SELECT unnest(?::VARCHAR[]) AS username
        ),
        targets AS (
            SELECT username, 'rare manual user' AS why FROM rare_users
            UNION ALL
            SELECT username, 'configured high-risk user' FROM high_risk
        )
        SELECT j.entry_ref,
               j.line_no,
               j.username,
               j.amount,
               t.why || ' (' || COALESCE(j.username, '?') || ')' AS flag_reason
        FROM journal_lines j
        JOIN targets t ON j.username = t.username
        WHERE j.is_manual
    """, [p.unusual_user_rare_threshold, config.risk_context.high_risk_users])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="unusual_users",
        flagged=flagged,
        output_table=TABLE,
        notes=f"rare ≤ {p.unusual_user_rare_threshold} manual lines; "
              f"high-risk list: {config.risk_context.high_risk_users or '[]'}",
    )
