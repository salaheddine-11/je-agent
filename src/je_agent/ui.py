"""JE Agent Review UI (Phase 3, DESIGN §3.3) — Streamlit, in-process with the
orchestrator (B1 single-writer preserved).

Run:  uv run streamlit run src/je_agent/ui.py
Screens: Configure & Upload · Run Monitor · Review · Workpaper
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from je_agent.config import load_config
from je_agent.document import build_facts_block
from je_agent.llm.diagnostics import test_openai_compatible_connection
from je_agent.orchestrator import OrchestrationError, Orchestrator
from je_agent.review import (
    acknowledge_dq_warnings,
    effective_decisions,
    ensure_review_schema,
    submit_decisions,
)
from je_agent.run_context import RunContext
from je_agent.store import RunStore
from je_agent.universe import select_universe
from je_agent.workspace import RunLock

st.set_page_config(page_title="JE Agent", page_icon="🔎", layout="wide")

RUNS_DIR = Path(os.environ.get("JEAGENT_RUNS_DIR", "runs"))

# ---------------------------------------------------------------------------
# session state
# ---------------------------------------------------------------------------

if "provider_ok" not in st.session_state:
    st.session_state.provider_ok = None
if "run_thread_done" not in st.session_state:
    st.session_state.run_thread_done = True


def _orch() -> Orchestrator:
    return Orchestrator(runs_root=RUNS_DIR)


def _list_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(p.name for p in RUNS_DIR.iterdir()
                  if (p / "runstore.sqlite").exists())


# ===========================================================================
# SCREEN 1 — Configure & Upload
# ===========================================================================

tab_cfg, tab_mon, tab_review, tab_wp = st.tabs(
    ["⚙️ Configure & Upload", "📡 Run Monitor", "🧐 Review", "📄 Workpaper"])

with tab_cfg:
    st.header("Engagement configuration")
    c1, c2 = st.columns(2)

    with c1:
        cfg_file = st.file_uploader("Engagement YAML", type=["yaml", "yml"])
        extract_file = st.file_uploader("Journal-entry extract (CSV)", type=["csv"])
        run_id_input = st.text_input(
            "Run ID",
            value="UI_RUN",
            help="Must match run_id in the YAML; used as folder name.")

    with c2:
        st.subheader("LLM provider")
        p_base = st.text_input("Base URL",
                               value="https://generativelanguage.googleapis.com/v1beta/openai")
        p_model = st.text_input("Model id", value="gemini-3.5-flash-lite")
        p_key = st.text_input("API key", type="password",
                              help="Free-tier keys work; stored only in this session.")
        if st.button("🔌 Test connection"):
            if not p_base or not p_model:
                st.error("Base URL and model are required.")
            else:
                with st.spinner("Pinging endpoint + probing tool support…"):
                    res = test_openai_compatible_connection(p_base, p_model, p_key or None)
                st.session_state.provider_ok = res
                if res.ok:
                    st.success(f"Connected ({res.latency_ms} ms) — replied {res.reply!r}")
                    ts = getattr(res, "tool_support", None)
                    if ts:
                        st.info(f"Function calling OK: {getattr(res, 'tools_note', '')}")
                    else:
                        st.warning(f"Tools probe: {getattr(res, 'tools_note', '')}")
                else:
                    st.error(f"{res.error_kind}: {(res.error_detail or '')[:300]}")

    if st.button("▶️ Start run", disabled=not (cfg_file and extract_file)):
        tmp_dir = Path(os.environ.get("JEAGENT_TMP", ".")) / "_ui_uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = tmp_dir / f"{run_id_input}.yaml"
        ext_path = tmp_dir / f"{run_id_input}.csv"
        cfg_path.write_bytes(cfg_file.getvalue())
        ext_path.write_bytes(extract_file.getvalue())

        # validate config before spawning
        try:
            config = load_config(cfg_path)
            if config.run_id != run_id_input:
                st.error(f"YAML run_id is '{config.run_id}' but you typed '{run_id_input}'.")
                st.stop()
        except Exception as e:
            st.error(f"Invalid config: {e}")
            st.stop()

        def _work():
            try:
                _orch().start_run(cfg_path, ext_path)
            except Exception as e:  # noqa: BLE001
                st.session_state.run_error = str(e)
            st.session_state.run_thread_done = True

        st.session_state.run_thread_done = False
        threading.Thread(target=_work, daemon=True).start()
        st.info(f"Run '{run_id_input}' started in background — watch Run Monitor.")

# ===========================================================================
# SCREEN 2 — Run Monitor
# ===========================================================================

with tab_mon:
    st.header("Run monitor")
    runs = _list_runs()
    if not runs:
        st.info("No runs yet — start one in Configure & Upload.")
    else:
        sel_run = st.selectbox("Run", runs)
        ctx = RunContext(RUNS_DIR / sel_run)
        store = RunStore(ctx.runstore_path)
        info = store.get_run(sel_run) or {}
        locked = RunLock.read(ctx.dir) is not None

        m1, m2, m3 = st.columns(3)
        m1.metric("Status", info.get("status", "?"))
        m2.metric("Phase", info.get("phase") or "—")
        m3.metric("Lock", "held" if locked else "free")

        # stale-lock recovery prompt (X4)
        if locked and RunLock.is_stale(ctx.dir):
            st.warning("A previous session crashed — this lock is stale.")
            if st.button("♻️ Recover from last checkpoint"):
                try:
                    _orch().recover_run(sel_run)
                    st.success("Recovered.")
                    st.rerun()
                except OrchestrationError as e:
                    st.error(str(e))

        st.subheader("Event timeline")
        events = pd.DataFrame(
            [(ts[:19], kind, detail or "") for ts, kind, detail in store.events(sel_run)],
            columns=["time", "event", "detail"])
        st.dataframe(events, use_container_width=True, height=260)

        try:
            con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
            rule_rows = con.execute("""
                SELECT json_extract(result_json,'$.flagged') AS flagged, tool
                FROM sqlite_master LIMIT 0
            """).fetchall() if False else None
            con.close()
        except Exception:
            pass

        # rule hit counts from the store
        try:
            rows = store.con.execute("""
                SELECT tool, CAST(json_extract(result_json,'$.flagged') AS INT) AS flagged
                FROM tool_calls WHERE phase='EXECUTE' AND outcome='ok'
                  AND result_json IS NOT NULL ORDER BY seq
            """).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["rule", "flagged"])
                st.bar_chart(df.set_index("rule"))
        except Exception:
            pass
        store.close()

# ===========================================================================
# SCREEN 3 — Review
# ===========================================================================

with tab_review:
    st.header("Review queue")
    runs = _list_runs()
    if not runs:
        st.info("No runs yet.")
    else:
        r_run = st.selectbox("Run", [r for r in runs], key="rev_run")
        ctx = RunContext(RUNS_DIR / r_run)
        store = RunStore(ctx.runstore_path)
        ensure_review_schema(store)

        try:
            con = duckdb.connect(str(ctx.duckdb_path), read_only=True)
            universe = select_universe(con, load_config(ctx.dir / "config.yaml"))
            facts = build_facts_block(con, load_config(ctx.dir / "config.yaml"),
                                      universe, None, store)
        except Exception as e:
            st.error(f"Universe unavailable: {e}")
            con.close(); store.close(); st.stop()

        eff = effective_decisions(store, r_run)
        pending = [e for e in universe.entries if e["entry_ref"] not in eff]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Universe", universe.selected)
        c2.metric("Decided", len(eff))
        c3.metric("Pending", len(pending))
        c4.metric("Progress",
                  f"{100 * len(eff) // max(1, universe.selected)}%")

        reviewer = st.text_input("Reviewer name", value="jdoe")

        st.subheader("Decide entries")
        edited = st.data_editor(
            pd.DataFrame([{
                "entry_ref": e["entry_ref"],
                "rules_hit": e["rules_hit"],
                "amount": round(e["abs_amount"], 2),
                "decision": "accept",
                "reason": "",
            } for e in pending]),
            column_config={
                "decision": st.column_config.SelectboxColumn(
                    options=["accept", "inspect", "override"], required=True),
            },
            disabled=["entry_ref", "rules_hit", "amount"],
            use_container_width=True, hide_index=True,
            key="decide_grid",
        )
        if st.button("💾 Submit decisions", disabled=not len(edited)):
            from je_agent.review import DecisionInput

            inputs, errors = [], []
            for row in edited.to_dict("records"):
                if row["decision"] == "override" and not str(row["reason"]).strip():
                    errors.append(row["entry_ref"])
                    continue
                inputs.append(DecisionInput(entry_ref=row["entry_ref"],
                                            decision=row["decision"],
                                            reason=row["reason"] or None))
            if errors:
                st.error(f"Override requires a reason for: {errors[:5]}")
            elif inputs:
                n = submit_decisions(store, r_run, reviewer, "declared", inputs)
                st.success(f"Recorded {n} hash-chained decisions.")
                st.rerun()

        st.subheader("DQ warnings — acknowledge (X3)")
        dq_note = st.text_area("Acknowledgment reason", height=60)
        dq_pick = st.multiselect(
            "Warning classes to acknowledge",
            ["dq_missing_fields", "dq_sign_convention", "dq_unbalanced_docs",
             "dq_period_coverage", "dq_duplicate_line_keys"])
        if st.button("Acknowledge DQ classes"):
            try:
                n, lims = acknowledge_dq_warnings(
                    store, r_run, reviewer, "declared",
                    [{"warning_id": w, "reason": dq_note or "reviewer acknowledged"} for w in dq_pick])
                st.success(f"Acknowledged {n}. Limitations raised: {lims or 'none'}")
            except Exception as e:
                st.error(str(e))
        con.close(); store.close()

# ===========================================================================
# SCREEN 4 — Workpaper
# ===========================================================================

with tab_wp:
    st.header("Workpaper")
    runs = _list_runs()
    if not runs:
        st.info("No runs yet.")
    else:
        w_run = st.selectbox("Run", runs, key="wp_run")
        ctx = RunContext(RUNS_DIR / w_run)
        wp_path = ctx.artifacts_dir / "workpaper.xlsx"
        flags_path = ctx.artifacts_dir / "flagged_entries.xlsx"

        st.subheader("Finalize gates")
        if st.button("🏁 Run finalize gates"):
            import subprocess
            import sys as _sys

            proc = subprocess.run(
                [_sys.executable, "-m", "je_agent.cli", "finalize", w_run,
                 "--runs-dir", str(RUNS_DIR)],
                capture_output=True, text=True, timeout=300)
            st.code(proc.stdout + ("\n" + proc.stderr if proc.returncode else ""))

        st.subheader("Downloads")
        col_a, col_b = st.columns(2)
        if flags_path.exists():
            col_a.download_button("⬇️ flagged_entries.xlsx",
                                  data=flags_path.read_bytes(),
                                  file_name="flagged_entries.xlsx")
        else:
            col_a.info("No flag export yet.")
        if wp_path.exists():
            col_b.download_button("⬇️ workpaper.xlsx",
                                  data=wp_path.read_bytes(),
                                  file_name="workpaper.xlsx")
        else:
            col_b.info("No workpaper yet — pass finalize first.")

        st.caption("This tool is a risk-flagging, prioritization, documentation, and "
                   "review-workflow system. It is not a substitute for substantive testing "
                   "or vouching. Every workpaper states §11 limitations explicitly.")
