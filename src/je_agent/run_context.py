"""Run folder layout (DESIGN §6.1) — self-contained evidence package."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .workspace import RunLock

RUN_ARTIFACTS = {
    "config.yaml",
    "extract.csv",
    "extract.sha256",
    "workspace.duckdb",
    "runstore.sqlite",
}


class RunContext:
    """Owns the run folder: layout creation, freezing, lock lifecycle."""

    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.llm_dir = self.dir / "llm"
        self.artifacts_dir = self.dir / "artifacts"
        self._lock: RunLock | None = None

    # -- layout ---------------------------------------------------------------

    def ensure_layout(self) -> None:
        for d in (self.dir, self.llm_dir, self.artifacts_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, runs_root: Path, run_id: str, config_yaml: str,
               extract_path: Path) -> "RunContext":
        """Create the run folder and freeze config + extract (§6.4 step 1)."""
        ctx = cls(runs_root / run_id)
        if ctx.dir.exists():
            raise FileExistsError(f"run folder already exists: {ctx.dir}")
        ctx.ensure_layout()
        (ctx.dir / "config.yaml").write_text(config_yaml, encoding="utf-8")
        shutil.copy2(extract_path, ctx.dir / "extract.csv")
        digest = sha256_file(ctx.dir / "extract.csv")
        (ctx.dir / "extract.sha256").write_text(digest, encoding="utf-8")
        return ctx

    # -- locks ------------------------------------------------------------------

    def acquire_lock(self) -> RunLock:
        if self._lock is None:
            self._lock = RunLock.acquire(self.dir)
        return self._lock

    def release_lock(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    # -- helpers -----------------------------------------------------------------

    @property
    def extract_path(self) -> Path:
        return self.dir / "extract.csv"

    @property
    def duckdb_path(self) -> Path:
        return self.dir / "workspace.duckdb"

    @property
    def runstore_path(self) -> Path:
        return self.dir / "runstore.sqlite"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
