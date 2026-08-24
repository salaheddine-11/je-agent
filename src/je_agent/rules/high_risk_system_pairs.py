"""high_risk_system_pairs — step 10, INFORMATIONAL, never gates (v1.3 W6).

System-generated documents by a configured high-risk user posting to an account
that is unusual FOR THAT USER: the account's share among that user's system
activity is below `unusual_account_share` (default 0.10). Narrows the unusual_pairs
blind spot. Feeds review salience only.
"""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_high_risk_system_pairs"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    share = float(getattr(config.rule_params, "unusual_account_share", 0.10))

    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        WITH user_profile AS (
            SELECT username,
                   account,
                   COUNT(*) AS n_acct,
                   SUM(COUNT(*)) OVER (PARTITION BY username) AS n_user
            FROM journal_lines
            WHERE NOT is_manual AND username IS NOT NULL
            GROUP BY username, account
        ),
        unusual_for_user AS (
            SELECT username, account
            FROM user_profile
            WHERE n_acct::DOUBLE / n_user < ?
        ),
        hrsp AS (
            SELECT j.entry_ref, j.line_no, j.username, j.amount
            FROM journal_lines j
            JOIN unusual_for_user u ON j.username = u.username AND j.account = u.account
            WHERE NOT j.is_manual
              AND j.username IN (SELECT unnest(?::VARCHAR[]))
        )
        SELECT entry_ref,
               line_no,
               username,
               amount,
               'system doc by high-risk user on account unusual for that user' AS flag_reason
        FROM hrsp
    """, [share, config.risk_context.high_risk_users])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="high_risk_system_pairs",
        flagged=flagged,
        output_table=TABLE,
        notes=f"INFORMATIONAL — never gating (W6); account unusual when its share of "
              f"the user's system activity < {share:.0%}",
    )
