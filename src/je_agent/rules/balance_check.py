"""flag_balance_check — step 6: documents whose lines do not net to zero within tolerance (A4)."""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_balance_check"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    tol = config.rule_params.balance_tolerance
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        WITH nets AS (
            SELECT entry_ref, SUM(amount) AS net, COUNT(*) AS n_lines
            FROM journal_lines
            GROUP BY entry_ref
        )
        SELECT n.entry_ref,
               MIN(j.line_no) AS line_no,
               MIN(j.username) AS username,
               n.net AS amount,
               'unbalanced document: net = ' || CAST(n.net AS VARCHAR) ||
                ' across ' || n.n_lines || ' lines' AS flag_reason
        FROM journal_lines j
        JOIN nets n USING (entry_ref)
        GROUP BY n.entry_ref, n.net, n.n_lines
        HAVING ABS(n.net) > ?
    """, [tol])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="balance_check",
        flagged=flagged,
        output_table=TABLE,
        notes=f"documents with |net| > {tol}",
    )
