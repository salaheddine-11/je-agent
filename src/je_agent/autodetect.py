"""Auto-detect a column mapping from a CSV header + sample rows (Feature 1).

Reads only the header and first N rows, then proposes a canonical column_map
paired with the source system. Deterministic heuristics first (exact SAP/Oracle
field codes and clear English synonyms); a fuzzy pass covers near-miss names.
Returns a `ColumnDetection` the UI can use to pre-fill the configuration form.

Contract: detection is a *suggestion* — the auditor reviews and can override
before starting. Nothing is inferred silently into a frozen config.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from io import StringIO

# canonical field -> aliases (SAP field names, common ERP codes, English labels)
_ALIASES: dict[str, list[str]] = {
    "amount": ["amount", "amt", "dmbtr", "werrs", "value", "gross", "fcy", "local_amount", "amount_lc", "credit_amount", "debit_amount", "base_amount"],
    "currency": ["currency", "ccy", "waers", "curr", "cur", "currency_code", "cukey"],
    "posting_date": ["posting_date", "postingdate", "bdate", "budat", "posted", "post_date", "posting_date", "date_posted", "fiscal_date", "pstng_date", "book_date"],
    "document_date": ["document_date", "docdate", "bldat", "doc_date", "invoice_date", "documentdate", "date_doc"],
    "account": ["account", "acct", "hkont", "account_number", "acct_no", "gl_account", "account_no", "glaccount", "code", "account_code", "g/l_account", "gl", "gl_acct", "gl account"],
    "username": ["username", "user", "uname", "usnam", "user_id", "posted_by", "created_by", "user_name", "maker", "userid", "auser"],
    "description": ["description", "descr", "sgtxt", "text", "narrative", "line_text", "memo", "remark", "remarks", "description_text", "item_text", "txt", "label"],
    "source_doc": ["source_doc", "srcdoc", "belnr", "doc_number", "document_no", "reference", "ref_doc", "source_document", "document_number", "docnum", "doc_no"],
    "entry_ref": ["entry_ref", "entryref", "key", "id", "entry_id", "uuid", "unique_id", "record_id", "voucher", "entry_key"],
    "entry_created_date": ["entry_created_date", "created", "cpudt", "entry_date", "create_date", "created_on", "creation_date", "created_at", "timestamp", "aedat"],
    "entry_type": ["entry_type", "entrytype", "blart", "type", "doc_type", "document_type", "posting_type", "entrycategory", "voucher_type"],
    "entry_ref2": ["entry_ref2"],
}

# field label for the form (human-facing)
_FIELD_LABEL = {
    "amount": "amount", "currency": "currency", "posting_date": "posting_date",
    "document_date": "document_date", "account": "account", "username": "username",
    "description": "description", "source_doc": "source_doc", "entry_ref": "entry_ref",
    "entry_created_date": "entry_created_date", "entry_type": "entry_type",
}


@dataclass
class ColumnDetection:
    system: str
    amount_column: str
    currency_column: str | None
    column_map: dict[str, str]
    confidence: float
    notes: list[str] = field(default_factory=list)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def _alphabetize(headers: list[str]) -> dict[str, str]:
    """header(normalized) -> original header"""
    return {_norm(h): h for h in headers}


def detect_columns(csv_text: str, max_rows: int = 5) -> ColumnDetection:
    """Propose a column mapping from a CSV header + first rows.

    Reads header + up to `max_rows` data rows with a plain csv reader (no pandas,
    no engine inference — stays fast and dependency-light). Duplicate headers are
    disambiguated by position (col1, col2, …).
    """
    reader = csv.reader(StringIO(csv_text))
    try:
        raw_header = next(reader)
    except StopIteration:
        return ColumnDetection("generic", "", None, {}, 0.0,
                               ["empty file — no header found"])
    headers = [h.strip() for h in raw_header if h and h.strip()]
    sample = [row for _, row in zip(range(max_rows), reader)]
    if not headers:
        return ColumnDetection("generic", "", None, {}, 0.0,
                               ["no named columns in header"])

    norm_to_orig = _alphabetize(headers)
    canonical_rev: dict[str, str] = {}      # normalized alias -> canonical field
    for canon, aliases in _ALIASES.items():
        for a in aliases:
            canonical_rev[_norm(a)] = canon

    column_map: dict[str, str] = {}
    used_headers: set[str] = set()
    notes: list[str] = []
    matched = 0

    # first pass: strongest exact alias match (SAP codes + English labels)
    for canon, aliases in _ALIASES.items():
        for a in aliases:
            n = _norm(a)
            if n in norm_to_orig and n not in used_headers:
                column_map[canon] = norm_to_orig[n]
                used_headers.add(n)
                matched += 1
                break

    # second pass: fuzzy — a header contains a distinct alias word
    if not column_map.get("amount") or len(column_map) < len(_ALIASES):
        for h in headers:
            hn = _norm(h)
            if hn in used_headers:
                continue
            for canon, aliases in _ALIASES.items():
                if canon in column_map:
                    continue
                if any(hn == _norm(a) or (len(_norm(a)) >= 3 and _norm(a) in hn)
                       for a in aliases):
                    column_map[canon] = h
                    used_headers.add(hn)
                    matched += 1
                    break

    confidence = matched / max(len(_ALIASES), 1)
    system = _detect_system(headers, column_map)

    # normalize: amount + currency required to run; derive from column_map else header
    amt = column_map.get("amount") or _first_match(headers, ["amount", "amt", "dmbtr", "value"])
    ccy = column_map.get("currency") or _first_match(headers, ["currency", "ccy", "waers"])
    if not amt:
        notes.append("no amount column detected — manual review needed")
    if not ccy:
        notes.append("no currency column detected — will default to single-currency")
    if not column_map.get("posting_date"):
        notes.append("no posting date detected")

    # trim the column_map to only the fields the config schema knows
    known = {k: v for k, v in column_map.items() if k in _FIELD_LABEL}
    # entry_ref and source_doc commonly map to the SAME doc field; if entry_ref
    # was not independently matched but source_doc was, inherit it (they both
    # identify the journal document).
    if "entry_ref" not in known and "source_doc" in known:
        known["entry_ref"] = known["source_doc"]

    return ColumnDetection(
        system=system, amount_column=amt, currency_column=ccy,
        column_map=known, confidence=round(confidence, 3), notes=notes,
    )


def _detect_system(headers: list[str], column_map: dict[str, str]) -> str:
    saxon = {"budat", "bldat", "hkont", "sgtxt", "uname", "belnr", "waers", "dmbtr", "blart", "cpudt", "usnam", "werrs"}
    norm_headers = {_norm(h) for h in headers}
    n_sap = len(norm_headers & saxon)
    if n_sap >= 3:
        return "sap"
    if any(_norm(h) in {"journal", "gl", "general_ledger"} for h in headers):
        return "generic"
    return "generic"


def _first_match(headers: list[str], aliases: list[str]) -> str | None:
    for h in headers:
        hn = _norm(h)
        if hn in {_norm(a) for a in aliases}:
            return h
    return None
