"""JE Agent CLI (Phase 1 §10.1): start / status / recover / export."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from je_agent.config import load_config
from je_agent.store import RunStore

app = typer.Typer(name="jeagent", help="JE Agent — Journal Entry Testing (Phase 1 core)")
console = Console()


@app.command()
def start(
    config: Path = typer.Option(..., "--config", "-c", help="Engagement YAML"),
    extract: Path = typer.Option(..., "--extract", "-e", help="Client journal-entry CSV"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r", help="Runs root folder"),
):
    """Start a run: INGEST → RISK_PLAN → EXECUTE → CROSS_REF."""
    from je_agent.ingest import sha256_of_file
    from je_agent.orchestrator import Orchestrator

    orch = Orchestrator(runs_root=runs_dir)
    with console.status("[bold green]running deterministic pipeline…"):
        run_id = orch.start_run(config, extract)
    info = orch.get_run(run_id)
    console.print(f"[bold green]✔[/] run [bold]{run_id}[/] complete — status: {info['status']}")
    _print_universe_table(runs_dir, run_id)


@app.command()
def status(
    run_id: str = typer.Argument(..., help="Run identifier"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r"),
):
    """Show run status + event timeline (read-only)."""
    from je_agent.orchestrator import Orchestrator

    info = Orchestrator(runs_root=runs_dir).get_run(run_id)
    console.print(f"run [bold]{info['run_id']}[/]: status=[cyan]{info['status']}[/] "
                  f"phase={info['phase']} locked={info['locked']}")
    for ts, kind, detail in info["events"]:
        console.print(f"  {ts[:19]}  {kind:<16} {detail or ''}")


@app.command("test-connection")
def test_connection(
    base_url: str = typer.Option(..., "--base-url", "-u", help="OpenAI-compatible base URL"),
    model: str = typer.Option(..., "--model", "-m", help="Model id as served by the endpoint"),
    api_key: str = typer.Option(None, "--api-key", "-k", help="API key (omit for local servers)"),
    env_key: str = typer.Option(None, "--env-key", help="Read the key from this env var instead"),
):
    """Test a provider connection before running: ping + tool-support probe."""
    import os

    from je_agent.llm.diagnostics import test_openai_compatible_connection

    key = api_key or (os.environ.get(env_key) if env_key else None)
    with console.status("[bold green]testing connection…"):
        result = test_openai_compatible_connection(base_url, model, key)
    console.print(result.summary())
    if hasattr(result, "tool_support"):
        if result.tool_support:
            console.print(f"[green]✔ tools:[/] {result.tools_note}")
        else:
            console.print(f"[red]✗ tools:[/] {result.tools_note} — "
                          "phase submission requires function calling")
    raise typer.Exit(code=0 if result.ok and getattr(result, "tool_support", False) else 1)


@app.command()
def recover(
    run_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Force recovery against a fresh lock (logged)"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r"),
):
    """Recover a crashed run from its last persisted stage (X4/Y7)."""
    from je_agent.orchestrator import Orchestrator

    if force:
        confirmed = typer.confirm("Force-recovery against a live/fresh lock will be logged as lock_forced. Continue?")
        if not confirmed:
            raise typer.Abort()
    info = Orchestrator(runs_root=runs_dir).recover_run(run_id, force=force)
    console.print(f"[bold green]✔[/] recovered — status={info['status']} phase={info['phase']}")


@app.command()
def export(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(None, "--out", "-o", help="Output xlsx path"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r"),
):
    """Export the flagged-entries Excel workpaper input."""
    import duckdb

    from je_agent.export import export_flagged_entries
    from je_agent.run_context import RunContext

    ctx = RunContext(runs_dir / run_id)
    out = out or ctx.artifacts_dir / "flagged_entries.xlsx"
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)  # Z5: reader is RO
    try:
        path = export_flagged_entries(con, out)
        console.print(f"[bold green]✔[/] exported: [underline]{path}[/]")
    finally:
        con.close()


@app.command()
def finalize(
    run_id: str = typer.Argument(...),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r"),
):
    """Run finalize gates 1-4 and write the workpaper xlsx on success."""
    import duckdb

    from je_agent.document import (
        active_limitations,
        build_facts_block,
        build_workpaper,
        finalize_gates,
    )
    from je_agent.ingest import ingest_extract  # noqa: F401
    from je_agent.run_context import RunContext
    from je_agent.schemas import Narrative, TriageReport
    from je_agent.universe import select_universe
    from je_agent.workpaper import write_workpaper

    ctx = RunContext(runs_dir / run_id)
    config = load_config(ctx.dir / "config.yaml")
    store = RunStore(ctx.runstore_path)

    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        universe = select_universe(con, config)
        facts = build_facts_block(con, config, universe, None, store)

        narrative = None
        narrative_path = ctx.llm_dir / "narrative.json"
        if narrative_path.exists():
            narrative = Narrative.model_validate_json(narrative_path.read_text(encoding="utf-8"))

        accepted = {row[0] for row in store.con.execute(
            "SELECT DISTINCT warning_id FROM dq_acknowledgments WHERE run_id = ?",
            [run_id]).fetchall()} | set(active_limitations(con, config, universe))

        report = finalize_gates(
            con, config, universe, narrative, facts, store,
            accepted_limitations=accepted, procedure_failures={})
    finally:
        con.close()

    table = Table(title="Finalize gates")
    table.add_column("gate")
    table.add_column("status")
    for name, ok in [
        ("1 review completeness", report.gate1_review_complete),
        ("2 procedure completeness", report.gate2_procedures_complete),
        ("3 narrative citations", report.gate3_citations_valid),
        ("4 limitation acceptance", report.gate4_limitations_accepted),
    ]:
        table.add_row(name, "[green]PASS[/]" if ok else "[red]FAIL[/]")
    console.print(table)
    for p in report.problems:
        console.print(f"[red]•[/] {p}")

    if not report.all_passed:
        raise typer.Exit(code=1)

    # rebuild a write connection for the workpaper payload
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        wp = build_workpaper(ctx, config, facts, narrative, store,
                             limitations_accepted=accepted)
    finally:
        con.close()
    out = write_workpaper(ctx.artifacts_dir / "workpaper.xlsx", wp)
    store.set_status(run_id, "finalized", "DOCUMENT")
    store.record_event(run_id, "finalize", f"workpaper written: {out.name}")
    console.print(f"[bold green]✔ run finalized[/] — workpaper: [underline]{out}[/]")

    # agent-produced audit report (HTML + PDF) — same visual deliverable every run
    try:
        from je_agent.report import export_pdf

        pdf_path = export_pdf(ctx.dir)
        store.record_event(run_id, "finalize", f"audit report: {pdf_path.name}")
        console.print(f"[bold green]✔ audit report[/] — [underline]{pdf_path}[/]")
    except Exception as e:  # noqa: BLE001 — report must not break finalize
        console.print(f"[yellow]⚠ report generation failed:[/] {e}")
    store.close()


def _print_universe_table(runs_dir: Path, run_id: str) -> None:
    import duckdb

    from je_agent.run_context import RunContext

    ctx = RunContext(runs_dir / run_id)
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
    try:
        table = Table(title="xref_ranked — top entries by rules hit")
        for h in ("entry_ref", "rules_hit", "abs_amount"):
            table.add_column(h)
        for row in con.execute("""
            SELECT entry_ref, rules_hit, abs_amount FROM xref_ranked
            ORDER BY rules_hit DESC, abs_amount DESC LIMIT 10
        """).fetchall():
            table.add_row(*[str(x) for x in row])
        console.print(table)
    finally:
        con.close()


if __name__ == "__main__":
    app()
