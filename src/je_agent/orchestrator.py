"""Orchestrator (DESIGN §3.1 contract, Phase 1 stages) — INGEST→RISK_PLAN→EXECUTE→CROSS_REF.

Single-writer per run folder (run.lock, W8/X4/Y7/Z5); every action recorded in the
run store at the moment it happens; stage-resumable via persisted state.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

from . import __version__
from .config import EngagementConfig, freeze_config, load_config
from .crossref import cross_reference_flags
from .export import export_flagged_entries
from .ingest import IngestReport, ingest_extract
from .plan import RiskPlan, constant_risk_plan
from .run_context import RunContext
from .store import RunStore
from .workspace import LockError, RecoveryLock, RunLock


class OrchestrationError(RuntimeError):
    pass


class Orchestrator:
    """Phase 1 orchestrator. The UI/CLI never computes — they call exactly these."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    # ------------------------------------------------------------------
    # start_run: freeze → lock → INGEST → RISK_PLAN → EXECUTE → CROSS_REF
    # ------------------------------------------------------------------

    def start_run(self, config_path: Path, extract_path: Path) -> str:
        config: EngagementConfig = load_config(Path(config_path))
        run_id = config.run_id
        run_dir = self.runs_root / run_id
        if run_dir.exists():
            raise OrchestrationError(
                f"run '{run_id}' already exists at {run_dir} "
                f"(use recover_run if a previous session crashed)")

        config_yaml, _digest = freeze_config(config)
        ctx = RunContext.create(self.runs_root, run_id, config_yaml, Path(extract_path))
        store = RunStore(ctx.runstore_path)
        try:
            try:
                lock = ctx.acquire_lock()
            except LockError as e:
                raise OrchestrationError(str(e)) from e

            store.record_run(run_id, extract_sha256=_sha(ctx.extract_path),
                             toolkit_version=__version__,
                             config_payload=config.model_dump(mode="json"))
            store.record_event(run_id, "phase_start", "INGEST")
            store.set_status(run_id, "running", "INGEST")

            seq = store.next_seq(run_id)
            t0 = time.perf_counter()
            report = ingest_extract(ctx, config)          # §6.4 sequence
            store.record_tool_call(
                run_id, seq, "INGEST", "load_journal_entries",
                {"extract": ctx.extract_path.name}, "ok",
                result={"population": report.raw_rows,
                        "canonical": report.canonical_rows,
                        "rejects": report.rejected_rows,
                        "dq": [w.warning_id for w in report.dq_warnings]},
                duration_ms=int((time.perf_counter() - t0) * 1000))

            store.record_event(run_id, "phase_end",
                               f"INGEST canonical={report.canonical_rows} "
                               f"rejects={report.rejected_rows}")

            # reject-rate pause gate (§6.4 step 6)
            if report.reject_rate > 0.02:
                store.record_event(run_id, "escalation",
                                   f"reject rate {report.reject_rate:.2%} > 2%")
                store.set_status(run_id, "failed", "INGEST")
                raise OrchestrationError(
                    f"reject rate {report.reject_rate:.2%} exceeds 2% — run paused for human confirmation")

            # ---- RISK_PLAN (constant producer; LLM swaps in here in Phase 2) ----
            store.record_event(run_id, "phase_start", "RISK_PLAN")
            store.set_status(run_id, "running", "RISK_PLAN")
            plan: RiskPlan = constant_risk_plan(config.risk_context)
            (ctx.llm_dir / "risk_plan.json").write_text(
                repr({"producer": plan.producer,
                      "selections": [vars(s) for s in plan.selections],
                      "plan_note": plan.plan_note}), encoding="utf-8")
            store.record_event(run_id, "phase_end", f"RISK_PLAN producer={plan.producer}")

            # ---- EXECUTE (plan is the script; §5.4) ------------------------------
            store.record_event(run_id, "phase_start", "EXECUTE")
            store.set_status(run_id, "running", "EXECUTE")
            con = duckdb.connect(str(ctx.duckdb_path))
            from .rules import execute_rules

            t0 = time.perf_counter()
            results = execute_rules(con, config)
            for r in results:
                ok = type(r).__name__ == "RuleResult"
                store.record_tool_call(
                    run_id, store.next_seq(run_id), "EXECUTE",
                    getattr(r, "rule", r.rule if hasattr(r, "rule") else "?"),
                    {}, "ok" if ok else "error",
                    result={"flagged": getattr(r, "flagged", None)} if ok else None,
                    error_code=None if ok else r.code,
                    duration_ms=None, seed=getattr(r, "seed", None))
            store.record_event(run_id, "phase_end", "EXECUTE")

            # ---- CROSS_REF ---------------------------------------------------------
            store.record_event(run_id, "phase_start", "CROSS_REF")
            store.set_status(run_id, "running", "CROSS_REF")
            n_universe = cross_reference_flags(con)
            store.record_tool_call(
                run_id, store.next_seq(run_id), "CROSS_REF", "cross_reference_flags",
                {}, "ok", result={"universe_entries": n_universe})
            export_flagged_entries(con, ctx.artifacts_dir / "flagged_entries.xlsx")
            con.close()
            store.record_event(run_id, "phase_end", f"CROSS_REF universe={n_universe}")

            # Phase 1 ends before TRIAGE (LLM) / REVIEW (human) stages.
            store.set_status(run_id, "awaiting_review", "CROSS_REF")
            store.record_event(run_id, "escalation",
                               "Phase 1 complete; TRIAGE/REVIEW arrive in Phase 2")
            lock.release()
            return run_id
        finally:
            store.close()

    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict:
        ctx = RunContext(self.runs_root / run_id)
        store = RunStore(ctx.runstore_path)
        try:
            info = store.get_run(run_id)
            if info is None:
                raise OrchestrationError(f"unknown run: {run_id}")
            info["locked"] = RunLock.read(ctx.dir) is not None
            info["events"] = store.events(run_id)
            return info
        finally:
            store.close()

    def recover_run(self, run_id: str, force: bool = False) -> dict:
        """X4/Y7 recovery: stale-lock detection under an atomic recovery-lock guard."""
        ctx = RunContext(self.runs_root / run_id)
        if not ctx.dir.exists():
            raise OrchestrationError(f"unknown run folder: {run_id}")

        with RecoveryLock(ctx.dir / "run.recovery.lock"):
            if RunLock.read(ctx.dir) is None:
                return self.get_run(run_id)     # nothing to recover
            if not RunLock.is_stale(ctx.dir) and not force:
                raise OrchestrationError(
                    "run lock is fresh/live; pass force=True with explicit confirmation")
            # DuckDB WAL recovery runs on open; checkpoint then verify readability.
            con = duckdb.connect(str(ctx.duckdb_path))
            con.execute("CHECKPOINT")
            n = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
            con.close()

            old_lock = RunLock.read(ctx.dir)
            RunLock.force_remove(ctx.dir)       # removes the stale marker
            store = RunStore(ctx.runstore_path)
            try:
                kind = "lock_forced" if force else "lock_recovered"
                store.record_event(run_id, kind,
                                   f"recovered workspace (journal_lines={n}); prior lock={old_lock}")
                status = store.get_run(run_id) or {}
                # resume point = last persisted phase (state machine resumes there)
                store.record_event(run_id, "escalation",
                                   f"resumable from phase={status.get('phase')}")
            finally:
                store.close()
        return self.get_run(run_id)


def _sha(path: Path) -> str:
    from .ingest import sha256_of_file

    return sha256_of_file(path)
