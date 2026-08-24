"""flag_unusual_pairs — step 8: debit/credit pairs unseen in the system-entry baseline (C3).

Semantics: a document's pair is "unusual" when the pair occurs in FEWER than
`min_baseline_count` OTHER unflagged system-generated documents. A candidate never
supports its own baseline (with min_baseline_count=1, a genuinely new pair must
still flag). Baseline inputs exclude documents flagged by canonical steps 1–7
(v1.6 Z2 fixes which rules feed this). Known blind spot (§11): system-entry pairs
form the baseline universe itself.
"""

from __future__ import annotations

import duckdb

from ..config import EngagementConfig
from .base import RuleResult

TABLE = "flags_unusual_pairs"

# canonical steps preceding unusual_pairs (its baseline-exclusion inputs)
BASELINE_EXCLUSION_SOURCES = [
    "flags_manual_entries",
    "flags_period_end",
    "flags_round_amounts",
    "flags_date_divergence",
    "flags_entry_splitting",
    "flags_balance_check",
    "flags_unusual_users",
]


def run(con: duckdb.DuckDBPyConnection, config: EngagementConfig) -> RuleResult:
    p = config.rule_params

    # Documents flagged by steps 1–7 (C3 exclusion input).
    con.execute(
        "CREATE OR REPLACE TEMP TABLE _flagged_docs AS "
        "SELECT NULL::TEXT AS entry_ref WHERE 1=0"
    )
    for t in BASELINE_EXCLUSION_SOURCES:
        exists = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [t]
        ).fetchone()[0]
        if exists:
            con.execute(f"INSERT INTO _flagged_docs SELECT DISTINCT entry_ref FROM {t}")

    con.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        WITH unflagged AS (
            SELECT j.*
            FROM journal_lines j
            LEFT JOIN _flagged_docs f USING (entry_ref)
            WHERE f.entry_ref IS NULL
        ),
        oriented AS (
            SELECT
                dr.entry_ref,
                dr.line_no,
                dr.username,
                CASE WHEN dr.amount > 0 THEN dr.account ELSE cr.account END AS debit_account,
                CASE WHEN dr.amount > 0 THEN cr.account ELSE dr.account END AS credit_account
            FROM journal_lines dr
            JOIN journal_lines cr
              ON dr.entry_ref = cr.entry_ref AND dr.line_no < cr.line_no
            WHERE ((dr.amount > 0 AND cr.amount < 0) OR (dr.amount < 0 AND cr.amount > 0))
        ),
        doc_pairs AS (
            SELECT entry_ref,
                   MIN(line_no) AS line_no,
                   MIN(username) AS username,
                   debit_account,
                   credit_account
            FROM oriented
            GROUP BY entry_ref, debit_account, credit_account
        ),
        sys_pair_docs AS (          -- distinct (doc, pair) among UNFLAGGED SYSTEM docs
            SELECT DISTINCT o.entry_ref, o.debit_account, o.credit_account
            FROM oriented o
            JOIN unflagged u USING (entry_ref)
            WHERE u.is_manual = FALSE
        ),
        pair_freq AS (              -- how many system docs use each pair
            SELECT debit_account, credit_account, COUNT(*) AS n_docs
            FROM sys_pair_docs
            GROUP BY debit_account, credit_account
        ),
        evaluated AS (
            SELECT dp.*,
                   COALESCE(pf.n_docs, 0)
                     - CASE WHEN EXISTS (
                           SELECT 1 FROM sys_pair_docs s
                           WHERE s.entry_ref = dp.entry_ref
                             AND s.debit_account = dp.debit_account
                             AND s.credit_account = dp.credit_account)
                       THEN 1 ELSE 0 END AS n_other_docs
            FROM doc_pairs dp
            LEFT JOIN pair_freq pf
              ON dp.debit_account = pf.debit_account
             AND dp.credit_account = pf.credit_account
        )
        SELECT entry_ref,
               line_no,
               username,
               NULL::DECIMAL(18,2) AS amount,
               'unusual pair: ' || debit_account || ' / ' || credit_account ||
                 ' occurs in ' || n_other_docs ||
                 ' other baseline document(s)' AS flag_reason
        FROM evaluated
        WHERE n_other_docs < ?
    """, [p.min_baseline_count])

    flagged = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    return RuleResult(
        rule="unusual_pairs",
        flagged=flagged,
        output_table=TABLE,
        notes=f"a pair is unusual when seen in < {p.min_baseline_count} OTHER unflagged "
              "system docs (self never baselines); blind spot: system pairs form the "
              "baseline universe (§11)",
    )
