"""Ingestion (DESIGN §6.4) — freeze, stage, map, reconcile, DQ profile (v1.6 Z1).

Mapping is SET-BASED SQL (TRY_ casts over the staged extract) so ingest scales to
the §9.4 budgets; Python never touches individual rows.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .config import EngagementConfig

# ---------------------------------------------------------------------------
# DQ warning classes (W2/X3/Y5 + v1.6 Z1)
# ---------------------------------------------------------------------------

DQ_SEVERITY = {
    "dq_duplicate_line_keys": ("critical", False),
    "dq_sign_convention": ("warning", False),
    "dq_period_coverage": ("critical", False),
    "dq_missing_fields": ("info", False),
    "dq_unbalanced_docs": ("critical", False),
    "dq_duplicate_extract": ("critical", True),
    "dq_extract_shortfall_declared": ("critical", True),  # v1.6 Z1, non-dismissible
    "dq_no_post_close_coverage": ("warning", False),      # v1.6 Z1
}

_DATE_FMTS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"]


@dataclass
class DqWarning:
    warning_id: str
    severity: str
    non_dismissible: bool
    count: int
    detail: str


@dataclass
class IngestReport:
    raw_rows: int = 0
    canonical_rows: int = 0
    rejected_rows: int = 0
    reject_rate: float = 0.0
    observed_min_posting_date: str | None = None
    observed_max_posting_date: str | None = None
    currencies: dict[str, int] = field(default_factory=dict)
    dq_warnings: list[DqWarning] = field(default_factory=list)
    extract_sha256: str = ""

    def summary(self) -> str:
        lines = [
            f"raw={self.raw_rows} canonical={self.canonical_rows} rejects={self.rejected_rows} "
            f"(rate {self.reject_rate:.2%})",
            f"posting dates: {self.observed_min_posting_date} .. {self.observed_max_posting_date}",
            f"currencies: {self.currencies or '{}'}",
        ]
        for w in self.dq_warnings:
            flag = " [non-dismissible]" if w.non_dismissible else ""
            lines.append(f"DQ {w.warning_id}: {w.severity}{flag} count={w.count} — {w.detail}")
        return "\n".join(lines)


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _date_sql(col_expr: str) -> str:
    """TRY multiple accepted formats -> DATE (NULL when unparseable)."""
    parts = [f"try_strptime({col_expr}, '{f}')" for f in _DATE_FMTS]
    return f"CAST(COALESCE({', '.join(parts)}) AS DATE)"


def _amount_norm_sql(col_expr: str) -> str:
    return f"""
        CASE
          WHEN regexp_matches({col_expr}, '^[-+]?[0-9]{{1,3}}(\\.[0-9]{{3}})+,[0-9]{{2}}$')
            THEN replace(replace({col_expr}, '.', ''), ',', '.')
          WHEN strpos({col_expr}, ',') > 0 AND strpos({col_expr}, '.') = 0
            THEN replace({col_expr}, ',', '.')
          ELSE replace(replace({col_expr}, ' ', ''), chr(160), '')
        END"""


def _like_pattern(pat: str) -> str:
    """Z3 wildcard pattern (* = any run) -> SQL LIKE pattern."""
    return pat.replace("*", "%")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_extract(ctx, config: EngagementConfig) -> IngestReport:
    report = IngestReport()
    con = duckdb.connect(str(ctx.duckdb_path))

    try:
        con.execute("SET preserve_insertion_order = true")

        # -- 1/2. stage verbatim (all TEXT) + stable staging sequence ----------
        con.execute(
            "CREATE OR REPLACE TABLE raw_extract AS "
            "SELECT row_number() OVER () AS staging_seq, t.* "
            "FROM read_csv(?, header = true, all_varchar = true) t",
            [str(ctx.extract_path)],
        )
        report.raw_rows = con.execute("SELECT count(*) FROM raw_extract").fetchone()[0]
        src_cols = [r[0] for r in con.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE table_name = 'raw_extract' AND column_name <> 'staging_seq'"
        ).fetchall()]
        have = {c.upper(): c for c in src_cols}

        def pick(*names: str | None) -> str | None:
            for n in names:
                if n and n.upper() in have:
                    return have[n.upper()]
            return None

        cm = config.source.column_map

        col_ref = pick(cm.entry_ref, cm.source_doc)
        col_line = pick("LINE")
        col_post = pick(cm.posting_date)
        col_docdate = pick(cm.document_date)
        col_created = pick(cm.entry_created_date)
        col_user = pick(cm.username)
        col_acct = pick(cm.account)
        col_desc = pick(cm.description)
        col_srdoc = pick(cm.source_doc)
        col_et = pick(cm.entry_type)
        col_cur = pick(config.source.currency_column) or pick("CURRENCY")
        col_amt = pick(config.source.amount_column)

        # mandatory-column validation (§8 INGEST: missing mandatory columns fail)
        missing = [
            label for label, col in (
                ("entry_ref/source_doc", col_ref),
                ("posting_date", col_post),
                (f"amount ({config.source.amount_column})", col_amt),
            ) if col is None
        ]
        if missing:
            raise ValueError(f"extract missing mandatory column(s): {', '.join(missing)}")

        c = {k: _q(v) for k, v in dict(
            ref=col_ref, line=col_line, post=col_post, docdate=col_docdate,
            created=col_created, user=col_user, acct=col_acct, desc=col_desc,
            srdoc=col_srdoc, et=col_et, cur=col_cur, amt=col_amt,
        ).items() if v}

        # -- 3. map + type-cast (set-based) ------------------------------------
        manual_types = [t.strip().lower() for t in config.rule_params.manual_entry_types]
        sys_like = [_like_pattern(p.strip()) for p in config.rule_params.system_user_patterns]

        et_on = "et" in c
        user_expr = f"nullif(trim({c.get('user')}), '')" if "user" in c else "NULL"
        et_expr = f"lower(nullif(trim({c['et']}), ''))" if et_on else "NULL"

        is_manual_sql = f"""
            CASE
              WHEN {("TRUE" if et_on else "FALSE")} AND {et_expr} IS NOT NULL
                THEN {et_expr} IN ({", ".join("'" + t + "'" for t in manual_types)})
              ELSE ({user_expr} IS NOT NULL AND NOT (
                    {' OR '.join(f"{user_expr} ILIKE '{p}'" for p in sys_like) or "FALSE"}))
            END"""

        amt_v = f"trim({c['amt']})"
        amount_sql = f"try_cast({_amount_norm_sql(amt_v)} AS DECIMAL(18,2))"

        con.execute("""
            CREATE OR REPLACE TEMP TABLE mapped AS
            SELECT
                staging_seq,
                nullif(trim({ref}), '')                        AS entry_ref,
                try_cast(trim({line}) AS INTEGER)              AS line_no_src,
                {post_date}                                    AS posting_date,
                {post_v}                                       AS posting_date_raw,
                {doc_date}                                     AS document_date,
                {created_date}                                 AS entry_created_date,
                {user_e}                                       AS username,
                {is_manual}                                    AS is_manual,
                CASE WHEN {et_on} AND {et_expr} IS NOT NULL
                     THEN 'source' ELSE 'derived' END          AS entry_type_source,
                nullif(trim({acct}), '')                       AS account,
                NULL                                           AS account_name,
                {amount}                                       AS amount,
                {amt_v}                                        AS amount_raw,
                {curr}                                         AS currency,
                {desc_e}                                       AS description,
                {srdoc}                                        AS source_doc
            FROM raw_extract
        """.format(
            ref=c["ref"],
            line=(c["line"] if "line" in c else "NULL"),
            post_date=(_date_sql(f"trim({c['post']})")),
            post_v=f"trim({c['post']})",
            doc_date=(_date_sql(f"trim({c['docdate']})") if "docdate" in c else "NULL"),
            created_date=(_date_sql(f"trim({c['created']})") if "created" in c else "NULL"),
            user_e=user_expr,
            is_manual=is_manual_sql,
            et_on=("TRUE" if et_on else "FALSE"),
            et_expr=(et_expr if et_on else "NULL"),
            acct=(c["acct"] if "acct" in c else "NULL"),
            amount=amount_sql,
            amt_v=amt_v,
            curr=(f"nullif(trim({c['cur']}), '')" if "cur" in c else "NULL"),
            desc_e=(f"trim({c['desc']})" if "desc" in c else "NULL"),
            srdoc=(f"nullif(trim({c['srdoc']}), '')" if "srdoc" in c else "NULL"),
        ))

        # rejects with first-failure reason (§6.4 step 3)
        json_pairs = ", ".join(
            f"'{name.lower()}', NULLIF(trim({_q(name)}), '')" for name in src_cols
        )
        con.execute(f"""
            CREATE OR REPLACE TABLE ingest_rejects AS
            SELECT m.staging_seq AS staging_row,
                   m.reason,
                   to_json(json_object({json_pairs})) AS raw_json
            FROM (
                SELECT staging_seq,
                       CASE
                         WHEN entry_ref IS NULL  THEN 'missing entry_ref / source_doc'
                         WHEN posting_date IS NULL AND (posting_date_raw IS NULL OR posting_date_raw = '')
                            THEN 'missing posting_date'
                         WHEN posting_date IS NULL
                            THEN 'unparseable posting_date: ' || posting_date_raw
                         WHEN amount IS NULL AND (amount_raw IS NULL OR amount_raw = '')
                            THEN 'missing amount'
                         WHEN amount IS NULL
                            THEN 'unparseable amount: ' || amount_raw
                       END AS reason
                FROM mapped
                WHERE entry_ref IS NULL OR posting_date IS NULL OR amount IS NULL
            ) m
            JOIN raw_extract r ON m.staging_seq = r.staging_seq
        """)

        # canonical: dedupe explicit key collisions (counted for DQ), then insert
        con.execute("""
            CREATE OR REPLACE TEMP TABLE canonical_dedup AS
            SELECT * FROM (
                SELECT m.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY entry_ref,
                                        COALESCE(line_no_src, 0) || ':' || staging_seq
                       ) AS rn
                FROM (
                    SELECT *,
                           COALESCE(line_no_src,
                               ROW_NUMBER() OVER (PARTITION BY entry_ref ORDER BY staging_seq)
                           ) AS line_no
                    FROM mapped
                    WHERE entry_ref IS NOT NULL AND posting_date IS NOT NULL AND amount IS NOT NULL
                ) m
            ) WHERE rn = 1
        """)

        con.execute("""
            CREATE TABLE journal_lines (
                staging_row        INTEGER,
                entry_ref          TEXT NOT NULL,
                line_no            INTEGER NOT NULL,
                posting_date       DATE,
                document_date      DATE,
                entry_created_date DATE,
                username           TEXT,
                is_manual          BOOLEAN,
                entry_type_source  TEXT CHECK (entry_type_source IN ('source', 'derived')),
                account            TEXT,
                account_name       TEXT,
                amount             DECIMAL(18,2),
                currency           TEXT,
                description        TEXT,
                source_doc         TEXT,
                PRIMARY KEY (entry_ref, line_no)
            )
        """)
        con.execute("""
            INSERT INTO journal_lines
            SELECT staging_seq, entry_ref, line_no, posting_date, document_date,
                   entry_created_date, username, is_manual, entry_type_source,
                   account, account_name, amount, currency, description, COALESCE(source_doc, entry_ref)
            FROM canonical_dedup
        """)

        report.canonical_rows = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
        n_rejects = con.execute("SELECT count(*) FROM ingest_rejects").fetchone()[0]
        staged = con.execute("SELECT count(*) FROM mapped").fetchone()[0]
        report.rejected_rows = n_rejects + (staged - n_rejects - report.canonical_rows)
        report.reject_rate = report.rejected_rows / report.raw_rows if report.raw_rows else 0.0

        dropped_dupes = max(0, staged - n_rejects - report.canonical_rows)
        if dropped_dupes > 0:
            sev, nd = DQ_SEVERITY["dq_duplicate_line_keys"]
            report.dq_warnings.append(DqWarning(
                "dq_duplicate_line_keys", sev, nd, dropped_dupes,
                f"{dropped_dupes} duplicate (entry_ref,line_no) rows collapsed"))

        # -- 5. reconcile: raw = canonical + rejects ---------------------------
        assert report.canonical_rows + report.rejected_rows == report.raw_rows, \
            f"reconciliation failed: {report.canonical_rows}+{report.rejected_rows} != {report.raw_rows}"

        # -- DQ stats -----------------------------------------------------------
        (min_pd, max_pd, n, n_neg, n_pos,
         n_missing_user, n_missing_desc, n_missing_curr) = con.execute("""
            SELECT min(posting_date), max(posting_date), count(*),
                   sum(CASE WHEN amount < 0 THEN 1 ELSE 0 END),
                   sum(CASE WHEN amount > 0 THEN 1 ELSE 0 END),
                   sum(CASE WHEN username IS NULL THEN 1 ELSE 0 END),
                   sum(CASE WHEN description IS NULL OR description = '' THEN 1 ELSE 0 END),
                   sum(CASE WHEN currency IS NULL OR currency = '' THEN 1 ELSE 0 END)
            FROM journal_lines
        """).fetchone()

        if n:
            report.observed_min_posting_date = str(min_pd)
            report.observed_max_posting_date = str(max_pd)

            currencies = con.execute("""
                SELECT COALESCE(currency, '(blank)'), count(*)
                FROM journal_lines GROUP BY 1 ORDER BY 2 DESC
            """).fetchall()
            report.currencies = dict(currencies)

            if n_neg == 0 and n_pos > 0:
                report.dq_warnings.append(_dq("dq_sign_convention",
                    f"zero negative amounts across {n} lines"))

            pe = _dt.date.fromisoformat(config.period_end)
            year_start = _dt.date(pe.year, 1, 1)
            if max_pd and max_pd < year_start:
                report.dq_warnings.append(_dq("dq_period_coverage",
                    f"max posting date {max_pd} predates {year_start}"))
            if min_pd and min_pd > pe:
                report.dq_warnings.append(_dq("dq_period_coverage",
                    f"min posting date {min_pd} is after period end {pe}"))

            missing_bits = []
            if n_missing_desc:
                missing_bits.append(f"description {n_missing_desc}/{n}")
            if n_missing_user:
                missing_bits.append(f"username {n_missing_user}/{n}")
            if n_missing_curr:
                missing_bits.append(f"currency {n_missing_curr}/{n}")
            if missing_bits:
                sev, nd = DQ_SEVERITY["dq_missing_fields"]
                report.dq_warnings.append(DqWarning(
                    "dq_missing_fields", sev, nd, len(missing_bits), "; ".join(missing_bits)))

        # -- v1.6 Z1: extract-coverage checks -----------------------------------
        declared = config.source.extract_through_date
        declared_d = _dt.date.fromisoformat(declared) if declared else None
        reversal_need = _dt.date.fromisoformat(config.period_end) + _dt.timedelta(
            days=config.rule_params.reversal_match_days)

        if declared_d and max_pd and max_pd < declared_d:
            report.dq_warnings.append(_dq("dq_extract_shortfall_declared",
                f"observed max posting date {max_pd} < declared extract_through_date {declared_d}"))

        eff_candidates = [x for x in (max_pd, declared_d) if x is not None]
        eff = min(eff_candidates) if eff_candidates else None
        if eff and eff < reversal_need:
            pe_date = _dt.date.fromisoformat(config.period_end)
            days_observed = max(0, (eff - pe_date).days)
            sev, nd = DQ_SEVERITY["dq_no_post_close_coverage"]
            report.dq_warnings.append(DqWarning(
                "dq_no_post_close_coverage", sev, nd, days_observed,
                f"post-close coverage ends {eff}; reversals needs data through {reversal_need} "
                f"({days_observed} days past period end observed)"))

        report.extract_sha256 = sha256_of_file(ctx.extract_path)
        return report

    finally:
        con.close()


def _dq(warning_id: str, detail: str) -> DqWarning:
    severity, non_dismissible = DQ_SEVERITY[warning_id]
    return DqWarning(warning_id, severity, non_dismissible, 1, detail)
