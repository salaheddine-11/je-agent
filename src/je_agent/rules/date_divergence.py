"""flag_date_divergence — step 4 (v1.2 V2): document/created vs posting date (backdating signal)."""

from __future__ import annotations

import datetime as _dt

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_date_divergence"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params
    pe = _dt.date.fromisoformat(config.period_end)

    # Branch 1 needs both dates present; branch 2 = created after period end while
    # posting is in-period (backdating signal).
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT entry_ref,
               line_no,
               username,
               amount,
               posting_date,
               document_date,
               entry_created_date,
               CASE
                 WHEN document_date IS NOT NULL AND
                      ABS(date_diff('day', document_date, posting_date)) > ?
                     THEN 'document/posting date divergence (' ||
                          date_diff('day', document_date, posting_date) || ' days)'
                 ELSE 'entry created after period end but posted in-period (backdating signal)'
               END AS flag_reason
        FROM journal_lines
        WHERE (document_date IS NOT NULL AND
               ABS(date_diff('day', document_date, posting_date)) > ?)
           OR (entry_created_date IS NOT NULL AND entry_created_date > CAST(? AS DATE))
    """, [p.doc_posting_gap_days, p.doc_posting_gap_days, pe])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="date_divergence",
        flagged=flagged,
        output_table=TABLE,
        notes="requires optional document_date / entry_created_date columns",
    )
