"""Run workspace + lock protocol (DESIGN §4.8, §6.1; W8/X4/Y7; v1.6 Z5)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil

HEARTBEAT_INTERVAL_S = 60     # Z5: five missed beats before staleness
STALE_THRESHOLD_S = 300       # X4 default
LOCK_NAME = "run.lock"
RECOVERY_LOCK_NAME = "run.recovery.lock"


class LockError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# PID liveness (Z5): psutil only, with create_time anti-reuse cross-check
# ---------------------------------------------------------------------------


def pid_alive(pid: int, since_create_time: float | None) -> bool:
    """True iff pid exists AND (when known) its create_time matches the lock's."""
    try:
        proc = psutil.Process(pid)
        if since_create_time is not None:
            return abs(proc.create_time() - since_create_time) < 2.0
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return False


# ---------------------------------------------------------------------------
# Lock files
# ---------------------------------------------------------------------------


class RunLock:
    """Active-run marker: PID + issuance time + heartbeat, exclusive-create (Z5).

    A watchdog daemon thread rewrites the heartbeat every HEARTBEAT_INTERVAL_S so
    long statements cannot orphan a healthy run. Heartbeat write failures are
    logged (stderr) but not fatal.
    """

    def __init__(self, path: Path, holder_pid: int | None = None):
        self.path = path
        self.pid = holder_pid if holder_pid is not None else os.getpid()
        self.create_time = psutil.Process(self.pid).create_time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- creation ----------------------------------------------------------

    @classmethod
    def acquire(cls, run_dir: Path) -> "RunLock":
        """Exclusive-create the lock or raise LockError if one already exists."""
        lock_path = run_dir / LOCK_NAME
        tmp = cls(lock_path)
        payload = {
            "pid": tmp.pid,
            "create_time": tmp.create_time,
            "heartbeat": time.time(),
        }
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except FileExistsError as e:
            raise LockError(f"active run lock already present: {lock_path}") from e
        except FileNotFoundError as e:
            raise LockError(f"run directory does not exist: {run_dir}") from e
        tmp._start_watchdog()
        return tmp

    # -- inspection ---------------------------------------------------------

    @staticmethod
    def read(run_dir: Path) -> dict | None:
        p = run_dir / LOCK_NAME
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"corrupt": True}

    @staticmethod
    def is_stale(run_dir: Path, threshold_s: int = STALE_THRESHOLD_S) -> bool:
        """Heartbeat age authoritative; PID liveness advisory (X4)."""
        data = RunLock.read(run_dir)
        if data is None or data.get("corrupt"):
            return True  # no/corrupt lock => nothing healthy holds it
        age = time.time() - float(data.get("heartbeat", 0))
        if age > threshold_s:
            return True
        ct = data.get("create_time")
        alive = pid_alive(int(data.get("pid", -1)), float(ct) if ct is not None else None)
        return not alive

    @staticmethod
    def force_remove(run_dir: Path) -> None:
        """Remove a stale marker (recovery path only — caller must hold run.recovery.lock)."""
        (Path(run_dir) / LOCK_NAME).unlink(missing_ok=True)

    # -- lifecycle -----------------------------------------------------------

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    # -- watchdog --------------------------------------------------------------

    def _start_watchdog(self) -> None:
        def beat() -> None:
            while not self._stop.wait(HEARTBEAT_INTERVAL_S):
                try:
                    payload = {
                        "pid": self.pid,
                        "create_time": self.create_time,
                        "heartbeat": time.time(),
                    }
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(payload), encoding="utf-8")
                    os.replace(tmp, self.path)
                except Exception as e:  # noqa: BLE001 — never fatal per Z5
                    print(f"[je-agent] heartbeat write failed: {e}", file=sys.stderr)

        self._thread = threading.Thread(target=beat, name="jeagent-heartbeat", daemon=True)
        self._thread.start()


# ---------------------------------------------------------------------------
# Recovery lock (Y7): atomic guard, only its holder may recover
# ---------------------------------------------------------------------------


class RecoveryLock:
    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def __enter__(self) -> "RecoveryLock":
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "ts": time.time()}, f)
        self._held = True
        return self

    def __exit__(self, *exc) -> None:
        if self._held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            self._held = False
