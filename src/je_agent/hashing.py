"""Hash-chain utilities (v1.6 Z6).

Chains are per-table, per-run. Genesis rows hash against prev_hash = "0"*64;
row_hash = SHA-256(prev_hash || 0x00 || canonical_json(payload)).

canonical_json: UTF-8, sorted keys, no insignificant whitespace — produced only by
canonical_json() so producers and verifiers cannot diverge.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

GENESIS_PREV_HASH = "0" * 64


def canonical_json(payload: Any) -> str:
    """UTF-8 JSON with sorted keys and compact separators. The one true serializer."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def row_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    """SHA-256(prev_hash || 0x00 || canonical_json(payload))."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


def genesis_row_hash(payload: dict[str, Any]) -> str:
    return row_hash(GENESIS_PREV_HASH, payload)


@dataclass
class ChainReport:
    table: str
    run_id: str
    length: int
    intact: bool
    first_bad_index: int | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        state = "verified" if self.intact else f"BROKEN at index {self.first_bad_index}"
        return f"chain {self.table}/{self.run_id}: {state} ({self.length} rows)"


def verify_chain(rows: list[dict[str, Any]], table: str, run_id: str) -> ChainReport:
    """Verify a hash chain over ordered rows (ascending id/seq).

    Each row must carry `row_hash`; every other key participates in the payload.
    """
    report = ChainReport(table=table, run_id=run_id, length=len(rows), intact=True)
    prev = GENESIS_PREV_HASH
    for i, r in enumerate(rows):
        stored = r.get("row_hash")
        if not stored:
            report.errors.append(f"row {i}: missing row_hash")
            report.intact = False
            if report.first_bad_index is None:
                report.first_bad_index = i
            continue
        payload = {k: v for k, v in r.items() if k != "row_hash"}
        expected = row_hash(prev, payload)
        if stored != expected:
            report.errors.append(f"row {i}: hash mismatch (expected {expected[:12]}…, got {stored[:12]}…)")
            report.intact = False
            if report.first_bad_index is None:
                report.first_bad_index = i
        # chain continues from the STORED hash so a single tampered row breaks
        # exactly once and everything after it too (tamper-evidence, not healing)
        prev = stored
    return report
