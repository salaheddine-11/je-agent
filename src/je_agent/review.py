"""REVIEW store (DESIGN §7.2, §8; W7/X3/Y2/Y5; v1.6 Z6).

Human-paced stage. Only the orchestrator writes; decision rows are hash-chained
per-table per-run (tamper-evident); supersede, never update; override requires a
reason; critical DQ acknowledgments raise finalize-gate-4 limitations;
dq_duplicate_extract is non-dismissible.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hashing import ChainReport, canonical_json, verify_chain
from .store import RunStore

REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reviewer_source TEXT NOT NULL,   -- 'declared' | 'sso'
    entry_ref TEXT NOT NULL,
    decision TEXT NOT NULL,          -- inspect | accept | override
    reason TEXT,                     -- mandatory on override
    supersedes INTEGER,
    row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dq_acknowledgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reviewer_source TEXT NOT NULL,
    warning_id TEXT NOT NULL,
    scope TEXT,
    reason TEXT NOT NULL,
    row_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS injection_dispositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    ts TEXT NOT NULL, reviewer TEXT NOT NULL,
    reviewer_source TEXT NOT NULL,
    event_ref TEXT NOT NULL,         -- reference to the prompt_injection_suspected event/entry
    disposition TEXT NOT NULL,       -- confirmed_suspicious | false_positive | not_relevant
    reason TEXT NOT NULL,
    row_hash TEXT NOT NULL
);
"""


class ReviewError(RuntimeError):
    pass


@dataclass
class DecisionInput:
    entry_ref: str
    decision: str                    # inspect | accept | override
    reason: str | None = None


def ensure_review_schema(store: RunStore) -> None:
    store.con.executescript(REVIEW_SCHEMA)
    store.con.commit()


# ---------------------------------------------------------------------------
# decisions (W7/Z6 chaining)
# ---------------------------------------------------------------------------


def submit_decisions(store: RunStore, run_id: str, reviewer: str,
                     reviewer_source: str, decisions: list[DecisionInput]) -> int:
    from datetime import datetime, timezone

    ensure_review_schema(store)
    prev = _last_hash(store, "review_decisions", run_id)
    n = 0
    for d in decisions:
        if d.decision == "override" and not (d.reason and d.reason.strip()):
            raise ReviewError(f"override of {d.entry_ref} requires a mandatory reason")
        if d.decision not in ("inspect", "accept", "override"):
            raise ReviewError(f"invalid decision {d.decision!r} for {d.entry_ref}")
        payload = {
            "run_id": run_id, "reviewer": reviewer, "reviewer_source": reviewer_source,
            "entry_ref": d.entry_ref, "decision": d.decision, "reason": d.reason,
        }
        h = _next_hash(prev, payload)
        store.con.execute(
            """INSERT INTO review_decisions
               (run_id, ts, reviewer, reviewer_source, entry_ref, decision, reason, supersedes, row_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            [run_id, datetime.now(timezone.utc).isoformat(), reviewer, reviewer_source,
             d.entry_ref, d.decision, d.reason, h])
        prev = h
        n += 1
    store.con.commit()
    return n


def effective_decisions(store: RunStore, run_id: str) -> dict[str, dict]:
    """Latest non-superseded decision per entry_ref."""
    ensure_review_schema(store)
    rows = store.con.execute("""
        SELECT r.entry_ref, r.decision, r.reason, r.reviewer, r.ts
        FROM review_decisions r
        WHERE r.run_id = ?
          AND r.id = (SELECT MAX(r2.id) FROM review_decisions r2
                      WHERE r2.run_id = r.run_id AND r2.entry_ref = r.entry_ref)
    """, [run_id]).fetchall()
    return {r[0]: {"decision": r[1], "reason": r[2], "reviewer": r[3], "ts": r[4]}
            for r in rows}


# ---------------------------------------------------------------------------
# DQ acknowledgments (X3/Y5)
# ---------------------------------------------------------------------------

NON_DISMISSIBLE = {"dq_duplicate_extract", "dq_extract_shortfall_declared"}
CRITICAL_CLASSES = {
    "dq_duplicate_line_keys", "dq_period_coverage", "dq_unbalanced_docs",
    "dq_duplicate_extract", "dq_extract_shortfall_declared",
}


def acknowledge_dq_warnings(store: RunStore, run_id: str, reviewer: str,
                            reviewer_source: str,
                            acks: list[dict]) -> tuple[int, list[str]]:
    """acks: [{warning_id, scope?, reason}] -> (accepted_count, raised_limitations).

    Critical classes additionally raise a gate-4 limitation (Y5).
    Non-dismissible classes are refused outright (X3).
    """
    from datetime import datetime, timezone

    ensure_review_schema(store)
    prev = _last_hash(store, "dq_acknowledgments", run_id)
    limitations: list[str] = []
    accepted = 0
    for ack in acks:
        wid = ack["warning_id"]
        if not (ack.get("reason") or "").strip():
            raise ReviewError(f"DQ acknowledgment of {wid} requires a mandatory reason")
        if wid in NON_DISMISSIBLE:
            raise ReviewError(f"{wid} is NON-DISMISSIBLE — it cannot be acknowledged away")
        payload = {
            "run_id": run_id, "reviewer": reviewer, "warning_id": wid,
            "scope": ack.get("scope"), "reason": ack["reason"],
        }
        h = _next_hash(prev, payload)
        store.con.execute(
            """INSERT INTO dq_acknowledgments
               (run_id, ts, reviewer, reviewer_source, warning_id, scope, reason, row_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [run_id, datetime.now(timezone.utc).isoformat(), reviewer, reviewer_source,
             wid, ack.get("scope"), ack["reason"], h])
        prev = h
        accepted += 1
        if wid in CRITICAL_CLASSES:
            limitations.append(
                f"acknowledged critical DQ warning '{wid}'"
                + (f" scoped to {ack['scope']}" if ack.get("scope") else ""))
    store.con.commit()
    return accepted, limitations


# ---------------------------------------------------------------------------
# injection dispositions (Y2: annotate, never delete)
# ---------------------------------------------------------------------------


def record_injection_disposition(store: RunStore, run_id: str, reviewer: str,
                                 reviewer_source: str, event_ref: str,
                                 disposition: str, reason: str) -> int:
    from datetime import datetime, timezone

    if disposition not in ("confirmed_suspicious", "false_positive", "not_relevant"):
        raise ReviewError(f"invalid disposition {disposition!r}")
    if not (reason or "").strip():
        raise ReviewError("injection disposition requires a mandatory reason")
    ensure_review_schema(store)
    prev = _last_hash(store, "injection_dispositions", run_id)
    payload = {"run_id": run_id, "reviewer": reviewer, "event_ref": event_ref,
               "disposition": disposition}
    h = _next_hash(prev, payload)
    store.con.execute(
        """INSERT INTO injection_dispositions
           (run_id, ts, reviewer, reviewer_source, event_ref, disposition, reason, row_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [run_id, datetime.now(timezone.utc).isoformat(), reviewer, reviewer_source,
         event_ref, disposition, reason, h])
    store.con.commit()
    cur = store.con.execute("SELECT last_insert_rowid()")
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# chain verification (QC report / AI Governance sheet)
# ---------------------------------------------------------------------------


def verify_all_chains(store: RunStore, run_id: str) -> dict[str, ChainReport]:
    """Verify chains over each table's canonical payload (the exact keys that were
    hashed at write time — excluding DB-managed id/ts and the hash itself)."""
    payload_keys = {
        "review_decisions": ["run_id", "reviewer", "reviewer_source",
                             "entry_ref", "decision", "reason"],
        "dq_acknowledgments": ["run_id", "reviewer", "warning_id", "scope", "reason"],
        "injection_dispositions": ["run_id", "reviewer", "event_ref", "disposition"],
    }
    out = {}
    for table, keys in payload_keys.items():
        try:
            cur = store.con.execute(
                f"SELECT {', '.join(keys)}, row_hash FROM {table} "
                f"WHERE run_id = ? ORDER BY id", [run_id])
            rows = [dict(zip([*keys, "row_hash"], r)) for r in cur.fetchall()]
        except Exception:
            out[table] = ChainReport(table=table, run_id=run_id, length=0, intact=True)
            continue
        if not rows:
            out[table] = ChainReport(table=table, run_id=run_id, length=0, intact=True)
            continue
        out[table] = verify_chain(rows, table=table, run_id=run_id)
    return out


# ---------------------------------------------------------------------------
# chain plumbing over the generic hashing utilities
# ---------------------------------------------------------------------------


def _last_hash(store: RunStore, table: str, run_id: str) -> str:
    try:
        row = store.con.execute(
            f"SELECT row_hash FROM {table} WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            [run_id]).fetchone()
    except Exception:
        return "0" * 64
    return row[0] if row else "0" * 64


def _next_hash(prev_hash: str, payload: dict) -> str:
    from .hashing import row_hash

    return row_hash(prev_hash, payload)


_ = canonical_json   # re-export parity with hashing module
