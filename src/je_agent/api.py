"""Phase 4 — REST API (DESIGN §10.4): FastAPI + API-key auth (SSO-ready seam).

Read-only engagement endpoints plus the full run lifecycle. Auth: X-API-Key
header against JEAGENT_API_KEYS (comma-separated). When JEAGENT_SSO_MODE=azure,
the /auth/* endpoints validate Entra ID JWTs instead (seam documented in DESIGN).

Run: uv run uvicorn je_agent.api:app --port 8300
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_config
from .document import build_facts_block, build_workpaper, finalize_gates
from .llm.diagnostics import test_openai_compatible_connection
from .report import export_pdf
from .review import (
    DecisionInput,
    acknowledge_dq_warnings,
    effective_decisions,
    verify_all_chains,
)
from .run_context import RunContext
from .store import RunStore
from .universe import select_universe
from .workspace import RunLock

app = FastAPI(title="JE Agent API", version="1.0.0",
              description="Journal-entry testing agent — Phase 4 REST surface")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("JEAGENT_CORS", "http://localhost:5173").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

# ---- serve the built web console from this same process (single-port mode) ----
_WEB_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
if _WEB_DIST.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _console():
        return FileResponse(_WEB_DIST / "index.html")


def _runs_root() -> Path:
    return Path(os.environ.get("JEAGENT_RUNS_DIR", "runs"))


def _api_keys() -> list[str]:
    raw = os.environ.get("JEAGENT_API_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def require_key(x_api_key: str = Header(default="")) -> None:
    keys = _api_keys()
    if not keys:
        raise HTTPException(503, "API auth not configured (set JEAGENT_API_KEYS)")
    if not any(hmac.compare_digest(x_api_key, k) for k in keys):
        raise HTTPException(401, "invalid or missing X-API-Key")


@app.get("/health")
def health():
    """Unauthenticated liveness probe."""
    return {"status": "ok", "version": "1.0.0",
            "sso_enabled": os.environ.get("JEAGENT_SSO_MODE", "").lower() == "azure"}


# ---------------------------------------------------------------- runs


@app.get("/api/runs", dependencies=[Depends(require_key)])
def list_runs():
    root = _runs_root()
    if not root.exists():
        return {"runs": []}
    runs = []
    for d in sorted(root.iterdir()):
        rs = d / "runstore.sqlite"
        if not rs.exists():
            continue
        store = RunStore(rs)
        try:
            info = store.get_run(d.name) or {}
            runs.append({"run_id": d.name, "status": info.get("status"),
                         "phase": info.get("phase")})
        finally:
            store.close()
    return {"runs": runs}


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_key)])
def run_detail(run_id: str):
    ctx = RunContext(_runs_root() / run_id)
    if not (ctx.dir / "runstore.sqlite").exists():
        raise HTTPException(404, f"unknown run {run_id}")
    store = RunStore(ctx.runstore_path)
    try:
        info = store.get_run(run_id) or {}
        events = [{"ts": t, "kind": k, "detail": d} for t, k, d in store.events(run_id)]
        locked = RunLock.read(ctx.dir) is not None
        stale = locked and RunLock.is_stale(ctx.dir)
        return {"run_id": run_id, **{k: info.get(k) for k in ("status", "phase")},
                "locked": locked, "lock_stale": bool(stale), "events": events}
    finally:
        store.close()


class StartBody(BaseModel):
    config_yaml: str


@app.post("/api/runs/start", dependencies=[Depends(require_key)])
def start_run(body: StartBody):
    """Persist the YAML, then launch `jeagent start` as a detached process."""
    from .config import EngagementConfig
    import yaml

    try:
        raw = yaml.safe_load(body.config_yaml)
        config = EngagementConfig.model_validate(raw)
    except Exception as e:
        raise HTTPException(422, f"invalid config: {e}")

    root = _runs_root()
    up_dir = root / "_uploads"
    up_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = up_dir / f"{config.run_id}.yaml"
    cfg_path.write_text(body.config_yaml, encoding="utf-8")
    extract_path = cfg_path.with_suffix(".csv")
    if not extract_path.exists():
        raise HTTPException(409, "upload the extract first: POST /api/runs/{id}/extract")

    subprocess.Popen(
        [sys.executable, "-m", "je_agent.cli", "start",
         "--config", str(cfg_path), "--extract", str(extract_path),
         "--runs-dir", str(root)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"started": config.run_id}


@app.post("/api/runs/{run_id}/extract", dependencies=[Depends(require_key)])
async def upload_extract(run_id: str, file: UploadFile = File(...)):
    up_dir = _runs_root() / "_uploads"
    up_dir.mkdir(parents=True, exist_ok=True)
    dest = up_dir / f"{run_id}.csv"
    dest.write_bytes(await file.read())
    return {"saved": dest.name, "bytes": len(await file.read()) if False else dest.stat().st_size}


# ---------------------------------------------------------------- review


@app.get("/api/runs/{run_id}/universe", dependencies=[Depends(require_key)])
def get_universe(run_id: str):
    import duckdb

    ctx = RunContext(_runs_root() / run_id)
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        sel = select_universe(con, load_config(ctx.dir / "config.yaml"))
        eff = effective_decisions(RunStore(ctx.runstore_path), run_id)
        entries = []
        for e in sel.entries:
            d = eff.get(e["entry_ref"])
            entries.append({**{"entry_ref": e["entry_ref"], "rules_hit": e["rules_hit"],
                               "abs_amount": e["abs_amount"]},
                            **({"decision": d["decision"], "reason": d["reason"]}
                               if d else {"decision": "pending"})})
        return {"selected": sel.selected, "entries": entries}
    finally:
        con.close()


@app.get("/api/runs/{run_id}/metrics", dependencies=[Depends(require_key)])
def run_metrics(run_id: str):
    """Aggregated engagement metrics for the Monitor + Report views."""
    import duckdb

    ctx = RunContext(_runs_root() / run_id)
    store = RunStore(ctx.runstore_path)
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        config = load_config(ctx.dir / "config.yaml")
        from .stats import run_benford

        rule_counts = {}
        for tool, n in store.con.execute(
                "SELECT tool, CAST(json_extract(result_json, '$.flagged') AS INT) "
                "FROM tool_calls WHERE phase='EXECUTE' AND outcome='ok' "
                "AND result_json IS NOT NULL ORDER BY seq").fetchall():
            rule_counts[tool] = n
        population = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
        flagged_docs = con.execute(
            "SELECT count(DISTINCT entry_ref) FROM xref_ranked").fetchone()[0]
        ben = run_benford(con, run_id)
        eff = effective_decisions(store, run_id)
        dec = {"inspect": 0, "accept": 0, "override": 0}
        for d in eff.values():
            dec[d["decision"]] = dec.get(d["decision"], 0) + 1
        sel = select_universe(con, config)
        return {
            "run_id": run_id, "status": (store.get_run(run_id) or {}).get("status"),
            "phase": (store.get_run(run_id) or {}).get("phase"),
            "population": population, "flagged_docs": flagged_docs,
            "universe_selected": sel.selected, "rule_counts": rule_counts,
            "decisions": dec, "benford": ben,
        }
    finally:
        con.close()
        store.close()


class DecisionsBody(BaseModel):
    reviewer: str
    decisions: list[dict]     # [{entry_ref, decision, reason}]


@app.post("/api/runs/{run_id}/decisions", dependencies=[Depends(require_key)])
def post_decisions(run_id: str, body: DecisionsBody):
    ctx = RunContext(_runs_root() / run_id)
    store = RunStore(ctx.runstore_path)
    try:
        inputs = [DecisionInput(entry_ref=d["entry_ref"], decision=d["decision"],
                                reason=d.get("reason")) for d in body.decisions]
        n = store.record_decisions_batch(run_id, body.reviewer, "declared", inputs)
        chains = verify_all_chains(store, run_id)
        return {"recorded": n,
                "chain_integrity": all(c.intact for c in chains.values())}
    finally:
        store.close()


class DQAckBody(BaseModel):
    reviewer: str
    acknowledgments: list[dict]   # [{warning_id, scope, reason}]


@app.post("/api/runs/{run_id}/dq-acknowledgments", dependencies=[Depends(require_key)])
def post_dq_acks(run_id: str, body: DQAckBody):
    ctx = RunContext(_runs_root() / run_id)
    store = RunStore(ctx.runstore_path)
    try:
        n, lims = acknowledge_dq_warnings(
            store, run_id, body.reviewer, "declared", body.acknowledgments)
        return {"acknowledged": n, "limitations_raised": lims}
    finally:
        store.close()


# ---------------------------------------------------------------- finalize


@app.post("/api/runs/{run_id}/finalize", dependencies=[Depends(require_key)])
def finalize_run(run_id: str):
    import duckdb

    ctx = RunContext(_runs_root() / run_id)
    config = load_config(ctx.dir / "config.yaml")
    store = RunStore(ctx.runstore_path)
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        universe = select_universe(con, config)
        facts = build_facts_block(con, config, universe, None, store)
        narrative = None
        np_ = ctx.llm_dir / "narrative.json"
        if np_.exists():
            from .schemas import Narrative

            narrative = Narrative.model_validate_json(np_.read_text(encoding="utf-8"))
        report = finalize_gates(con, config, universe, narrative, facts, store,
                                accepted_limitations=set(), procedure_failures={})
        if not report.all_passed:
            return {"finalized": False, "gates": {
                "gate1": report.gate1_review_complete,
                "gate2": report.gate2_procedures_complete,
                "gate3": report.gate3_citations_valid,
                "gate4": report.gate4_limitations_accepted},
                "problems": report.problems}
        wp = build_workpaper(ctx, config, facts, narrative, store,
                             limitations_accepted=set())
        from .workpaper import write_workpaper

        write_workpaper(ctx.artifacts_dir / "workpaper.xlsx", wp)
        pdf = export_pdf(ctx.dir)
        store.set_status(run_id, "finalized", "DOCUMENT")
        store.record_event(run_id, "finalize", f"workpaper + {pdf.name} written via API")
        return {"finalized": True,
                "artifacts": ["workpaper.xlsx", pdf.name]}
    finally:
        con.close()
        store.close()


# ---------------------------------------------------------------- artifacts


@app.get("/api/runs/{run_id}/artifacts/{name}", dependencies=[Depends(require_key)])
def download_artifact(run_id: str, name: str):
    from fastapi.responses import FileResponse

    allowed = {"report.pdf": "application/pdf",
               "report.html": "text/html",
               "flagged_entries.xlsx":
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "workpaper.xlsx":
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if name not in allowed:
        raise HTTPException(400, f"unknown artifact {name}")
    path = _runs_root() / run_id / "artifacts" / name
    if not path.exists():
        raise HTTPException(404, "artifact not generated yet")
    return FileResponse(path, media_type=allowed[name], filename=name)


# ---------------------------------------------------------------- diagnostics


class ConnTestBody(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None


@app.post("/api/provider/test-connection", dependencies=[Depends(require_key)])
def provider_test(body: ConnTestBody):
    res = test_openai_compatible_connection(body.base_url, body.model, body.api_key)
    out = {"ok": res.ok, "latency_ms": res.latency_ms, "reply": res.reply,
           "error_kind": res.error_kind, "error_detail": res.error_detail}
    if hasattr(res, "tool_support"):
        out["tool_support"] = res.tool_support
        out["tools_note"] = res.tools_note
    return out
