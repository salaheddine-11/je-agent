"""Run store (DESIGN §7) — Phase 1 subset: runs, tool_calls, events (+ chain utilities).

SQLite WAL inside each run folder; only the orchestrator writes; writes land at
the moment of action (crash-safe history).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .hashing import canonical_json, genesis_row_hash, row_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL,   -- started|running|awaiting_review|finalized|failed
    phase           TEXT,
    created_at      TEXT NOT NULL,
    extract_sha256  TEXT NOT NULL,
    toolkit_version TEXT NOT NULL,
    model_id        TEXT,            -- NULL in Phase 1 (deterministic core)
    config_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    seq INTEGER NOT NULL, ts TEXT NOT NULL, phase TEXT NOT NULL,
    tool TEXT NOT NULL, params_json TEXT NOT NULL,
    outcome TEXT NOT NULL,           -- ok | error
    error_code TEXT, result_json TEXT,
    duration_ms INTEGER, seed TEXT
);

CREATE TABLE IF NOT EXISTS llm_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    phase TEXT NOT NULL, turn INTEGER NOT NULL, ts TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    stop_reason TEXT, input_tokens INTEGER, output_tokens INTEGER,
    model_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,              -- phase_start|phase_end|failure|escalation|finalize|lock_recovered|lock_forced
    detail TEXT
);
"""


class RunStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    # -- runs ---------------------------------------------------------------

    def record_run(self, run_id: str, extract_sha256: str, toolkit_version: str,
                   config_payload: dict, model_id: str | None = None) -> None:
        from datetime import datetime, timezone

        self.con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, 'started', NULL, ?, ?, ?, ?, ?)",
            [run_id, datetime.now(timezone.utc).isoformat(), extract_sha256,
             toolkit_version, model_id, canonical_json(config_payload)],
        )
        self.con.commit()

    def set_status(self, run_id: str, status: str, phase: str | None = None) -> None:
        self.con.execute("UPDATE runs SET status = ?, phase = ? WHERE run_id = ?",
                         [status, phase, run_id])
        self.con.commit()

    def get_run(self, run_id: str) -> dict | None:
        cur = self.con.execute("SELECT run_id, status, phase, created_at, extract_sha256, "
                               "toolkit_version, model_id FROM runs WHERE run_id = ?", [run_id])
        row = cur.fetchone()
        if row is None:
            return None
        keys = ["run_id", "status", "phase", "created_at", "extract_sha256",
                "toolkit_version", "model_id"]
        return dict(zip(keys, row))

    # -- tool calls -------------------------------------------------------------

    def record_tool_call(self, run_id: str, seq: int, phase: str, tool: str,
                         params: dict, outcome: str, result: dict | None = None,
                         error_code: str | None = None, duration_ms: int | None = None,
                         seed: str | None = None) -> None:
        import json
        from datetime import datetime, timezone

        self.con.execute(
            "INSERT INTO tool_calls (run_id, seq, ts, phase, tool, params_json, outcome,"
            " error_code, result_json, duration_ms, seed)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [run_id, seq, datetime.now(timezone.utc).isoformat(), phase, tool,
             canonical_json(params), outcome, error_code,
             json.dumps(result) if result is not None else None,
             duration_ms, seed],
        )
        self.con.commit()

    def next_seq(self, run_id: str) -> int:
        cur = self.con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM tool_calls "
                               "WHERE run_id = ?", [run_id])
        return cur.fetchone()[0]

    # -- events -------------------------------------------------------------------

    def record_event(self, run_id: str, kind: str, detail: str | None = None) -> None:
        from datetime import datetime, timezone

        self.con.execute(
            "INSERT INTO events (run_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
            [run_id, datetime.now(timezone.utc).isoformat(), kind, detail],
        )
        self.con.commit()

    def record_decisions_batch(self, run_id: str, reviewer: str,
                               basis: str, inputs: list) -> int:
        """API-facing batch wrapper around review.submit_decisions."""
        from .review import submit_decisions

        return submit_decisions(self, run_id, reviewer, basis, inputs)

    def events(self, run_id: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, detail FROM events WHERE run_id = ? ORDER BY id", [run_id]
        ).fetchall()

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass


__all__ = ["RunStore", "genesis_row_hash", "row_hash"]
