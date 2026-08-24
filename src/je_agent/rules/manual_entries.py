"""flag_manual_entries — step 1 of canonical order (DESIGN §5.6)."""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_manual_entries"


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT entry_ref,
               line_no,
               username,
               amount,
               'manual entry (' || entry_type_source || ')' AS flag_reason
        FROM journal_lines
        WHERE is_manual
    """)
    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    derived = con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE flag_reason LIKE '%derived%'"
    ).fetchone()[0]
    return RuleResult(
        rule="manual_entries",
        flagged=flagged,
        output_table=TABLE,
        notes=f"{flagged} manual lines ({derived} via derived heuristic)",
    )
