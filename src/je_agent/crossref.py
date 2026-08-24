"""cross_reference_flags — union + rank flag tables into xref_ranked (DESIGN §5.1, §8 CROSS_REF).

Rank: rules_hit DESC, then abs(amount) DESC (§8). Gating universe = the 9 gating
rules; high_risk_system_pairs is informational and never gates (W6).
"""

from __future__ import annotations

import duckdb

GATING_FLAG_TABLES = [
    "flags_manual_entries",
    "flags_period_end",
    "flags_round_amounts",
    "flags_date_divergence",
    "flags_entry_splitting",
    "flags_balance_check",
    "flags_unusual_users",
    "flags_unusual_pairs",
    "flags_reversals",
]
INFORMATIONAL_FLAG_TABLES = ["flags_high_risk_system_pairs"]


def cross_reference_flags(con: duckdb.DuckDBPyConnection) -> int:
    """Build xref_ranked; returns the number of distinct flagged entries."""
    parts = []
    for t in GATING_FLAG_TABLES:
        exists = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [t]
        ).fetchone()[0]
        if exists:
            parts.append(f"SELECT entry_ref, line_no, flag_reason, '{t}' AS src_table FROM {t}")
    if not parts:
        con.execute("""
            CREATE OR REPLACE TABLE xref_ranked (
                entry_ref TEXT, line_no INTEGER, rules_hit INTEGER,
                abs_amount DECIMAL(18,2), amount DECIMAL(18,2),
                flag_reasons TEXT, selection_basis TEXT
            )
        """)
        return 0

    union_sql = "\nUNION ALL\n".join(parts)
    con.execute(f"""
        CREATE OR REPLACE TABLE xref_ranked AS
        WITH hits AS ({union_sql}),
        per_line AS (
            SELECT entry_ref,
                   line_no,
                   COUNT(DISTINCT src_table) AS rules_hit,
                   STRING_AGG(DISTINCT flag_reason, ' | ' ORDER BY flag_reason) AS flag_reasons
            FROM hits
            GROUP BY entry_ref, line_no
        ),
        doc_amount AS (
            SELECT entry_ref, MAX(ABS(amount)) AS abs_amount, MAX(amount) AS amount
            FROM journal_lines
            GROUP BY entry_ref
        )
        SELECT pl.entry_ref,
               pl.line_no,
               pl.rules_hit,
               da.abs_amount,
               da.amount,
               pl.flag_reasons,
               'targeted' AS selection_basis
        FROM per_line pl
        LEFT JOIN doc_amount da USING (entry_ref)
        ORDER BY pl.rules_hit DESC, da.abs_amount DESC
    """)
    return con.execute("SELECT count(DISTINCT entry_ref) FROM xref_ranked").fetchone()[0]
