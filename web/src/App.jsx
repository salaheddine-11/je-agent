import { useEffect, useState } from "react";
import { api, BASE } from "./api";

const INK = "#111827", SLATE = "#4b5563", FAINT = "#9ca3af", HAIR = "#e5e7eb",
      PAPER = "#f6f7f8", CARD = "#fff", AMBER = "#b45309";
const OI_VERM = "#D55E00", OI_GREEN = "#009E73";

const btn = { background: INK, color: "#fff", border: "none", borderRadius: 7,
              padding: "9px 16px", fontSize: 13, fontWeight: 650, cursor: "pointer" };
const btnGhost = { ...btn, background: "#fff", color: INK, border: `1.2px solid ${INK}` };
const btnSmall = { ...btnGhost, padding: "4px 10px", fontSize: 11.5, background: INK, color: "#fff", border: "none" };
const input = { border: `1px solid ${HAIR}`, borderRadius: 7, padding: "9px 12px",
                fontSize: 13, width: "100%", boxSizing: "border-box", background: "#fff" };
const card = { background: CARD, border: `1px solid ${HAIR}`, borderRadius: 8,
               padding: 20, marginBottom: 14 };
const label = { fontSize: 10.5, fontWeight: 700, letterSpacing: 1.2,
                textTransform: "uppercase", color: SLATE, marginBottom: 6, display: "block" };
const mono = "Consolas, monospace";

function chip(text, opts = {}) {
  return <span style={{
    fontSize: 10.5, fontWeight: 700, padding: "2px 10px", borderRadius: 999,
    ...opts }}>{text}</span>;
}
function tup(s) { return typeof s === "string" ? s.toUpperCase() : s; }

// ————————————————————————————— LOGIN
function Login({ onLogin }) {
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const [sso, setSso] = useState(false);
  useEffect(() => {
    fetch(`${BASE}/health`).then(r => r.json())
      .then(h => setSso(!!h.sso_enabled)).catch(() => {});
  }, []);
  const tryKey = async () => {
    sessionStorage.setItem("jeagent_key", key);
    try { await api.runs(); onLogin(); }
    catch (e) { setErr(e.message); sessionStorage.removeItem("jeagent_key"); }
  };
  return (
    <div style={{ maxWidth: 360, margin: "90px auto" }}>
      <div style={{ fontSize: 10.5, letterSpacing: 2.6, textTransform: "uppercase",
                    color: SLATE, marginBottom: 8 }}>JE Agent · ISA 240 / AS 2401</div>
      <h1 style={{ fontSize: 26, margin: "0 0 20px" }}>Sign in</h1>
      <input style={input} type="password" placeholder="API key"
             value={key} onChange={e => setKey(e.target.value)}
             onKeyDown={e => e.key === "Enter" && tryKey()} />
      {err && <p style={{ color: "#b91c1c", fontSize: 12.5 }}>{err}</p>}
      <button style={{ ...btn, marginTop: 14, width: "100%" }} onClick={tryKey}>Continue</button>
      {sso && <p style={{ color: SLATE, fontSize: 11.5, marginTop: 14 }}>
        Corporate single sign-on (Microsoft Entra ID) is enabled on this server.</p>}
    </div>
  );
}

// ————————————————————————————— CONFIGURE (provider + test connection)
function Configure() {
  const [base, setBase] = useState("https://generativelanguage.googleapis.com/v1beta/openai");
  const [model, setModel] = useState("gemini-3.5-flash-lite");
  const [key, setKey] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true); setRes(null);
    try { setRes({ ok: true, data: await api.testConnection({ base_url: base, model, api_key: key }) }); }
    catch (e) { setRes({ ok: false, err: e.message }); }
    setBusy(false);
  };
  return (
    <div style={card}>
      <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "0 0 16px" }}>Model connection</h2>
      <p style={{ color: SLATE, fontSize: 12.5, margin: "0 0 16px" }}>
        Any OpenAI-compatible endpoint: Gemini, Ollama, vLLM, LM Studio, OpenRouter, Azure.
        Verify credentials before starting a run.</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div><label style={label}>Base URL</label>
          <input style={input} value={base} onChange={e => setBase(e.target.value)} /></div>
        <div><label style={label}>Model ID</label>
          <input style={input} value={model} onChange={e => setModel(e.target.value)} /></div>
      </div>
      <div style={{ marginTop: 12 }}><label style={label}>API key</label>
        <input style={input} type="password" placeholder="(session only)" value={key}
               onChange={e => setKey(e.target.value)} /></div>
      <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
        <button style={btn} onClick={test} disabled={busy}>
          {busy ? "Testing…" : "🔌 Test connection"}</button>
        {res && res.ok && (
          <span style={{ fontSize: 12.5, color: OI_GREEN, fontWeight: 650 }}>
            ✔ {res.data.latency_ms} ms · {res.data.reply} · tools {res.data.tool_support ? "OK" : "n/a"}</span>)}
        {res && !res.ok && <span style={{ fontSize: 12.5, color: OI_VERM }}>✖ {res.err}</span>}
      </div>
    </div>
  );
}

const field = { ...input, marginBottom: 4 };
const lgrid = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 };

function ConfigForm({ config, setConfig, onAutodetect, autodetecting, detection }) {
  const set = (k) => (e) => setConfig({ ...config, [k]: e.target.value });
  const setCol = (k) => (e) => setConfig({
    ...config,
    column_map: { ...config.column_map, [k]: e.target.value } });
  const users = config.high_risk_users.join(", ");
  return (
    <div style={{ background: CARD, border: `1px solid ${HAIR}`, borderRadius: 8, padding: 20, marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                     margin: 0 }}>Engagement</h3>
        {onAutodetect && (
          <button style={btnSmall} onClick={onAutodetect} disabled={autodetecting}>
            {autodetecting ? "Detecting…" : "✨ Auto-detect from CSV"}</button>)}
      </div>
      {detection && (
        <p style={{ fontSize: 11.5, color: SLATE, margin: "0 0 10px" }}>
          Auto-detected column mapping (confidence {(detection.confidence * 100).toFixed(0)}%).
          Review and adjust if needed.{detection.notes?.length ? ` ${detection.notes.join(" ")}` : ""}</p>)}
      <div style={lgrid}>
        <div><label style={label}>Run ID</label>
          <input style={field} value={config.run_id} onChange={set("run_id")} /></div>
        <div><label style={label}>Period end</label>
          <input style={field} type="date" value={config.period_end} onChange={set("period_end")} /></div>
      </div>

      <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "18px 0 14px" }}>Materiality</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 4 }}>
        <div><label style={label}>Overall</label>
          <input style={field} type="number" value={config.overall} onChange={set("overall")} /></div>
        <div><label style={label}>Performance</label>
          <input style={field} type="number" value={config.performance} onChange={set("performance")} /></div>
        <div><label style={label}>Currency</label>
          <input style={field} value={config.currency} onChange={set("currency")} /></div>
      </div>

      <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "18px 0 14px" }}>Source system</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <div><label style={label}>System</label>
          <select style={field} value={config.system} onChange={set("system")}>
            <option value="sap">SAP</option><option value="oracle">Oracle</option>
            <option value="generic">Generic</option></select></div>
        <div><label style={label}>Amount column</label>
          <input style={field} value={config.amount_column} onChange={set("amount_column")} /></div>
        <div><label style={label}>Currency column</label>
          <input style={field} value={config.currency_column} onChange={set("currency_column")} /></div>
      </div>

      <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "18px 0 14px" }}>Column mapping</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        {[["posting_date", "Posting date"], ["document_date", "Document date"], ["account", "Account"],
          ["username", "Username"], ["description", "Description"], ["source_doc", "Source doc"],
          ["entry_ref", "Entry ref"], ["entry_created_date", "Created date"], ["entry_type", "Entry type"]].map(([k, t]) => (
          <div key={k}><label style={label}>{t}</label>
            <input style={field} value={config.column_map[k] || ""} onChange={setCol(k)} /></div>))}
      </div>

      <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "18px 0 14px" }}>Risk</h3>
      <div style={lgrid}>
        <div><label style={label}>High-risk users (comma separated)</label>
          <input style={field} value={users}
                 onChange={e => setConfig({ ...config, high_risk_users:
                   e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} /></div>
        <div><label style={label}>Universe size cap</label>
          <input style={field} type="number" value={config.max_universe_size}
                 onChange={e => setConfig({ ...config, max_universe_size: +e.target.value })} /></div>
      </div>

      <h3 style={{ fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: SLATE,
                   margin: "18px 0 14px" }}>Review</h3>
      <div style={{ display: "flex", gap: 8 }}>
        {["human", "ai"].map(m => (
          <button key={m} onClick={() => setConfig({ ...config, review_mode: m })}
                  style={{
                    ...(btnSmall), flex: 1,
                    background: config.review_mode === m ? INK : "#fff",
                    color: config.review_mode === m ? "#fff" : SLATE,
                    border: `1px solid ${config.review_mode === m ? INK : HAIR}` }}>
            {m === "human" ? "👤 Human review" : "🤖 AI review"}</button>))}
      </div>
      {config.review_mode === "ai" && (
        <p style={{ fontSize: 11.5, color: SLATE, margin: "8px 0 0" }}>
          The engine auto-decides inspect/accept from triage (reviewer "ai-reviewer"). Only for
          practice/demo or clean populations — AI review is not equivalent to human substantive testing.</p>)}
    </div>
  );
}

function NewEngagement({ onStarted }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [config, setConfig] = useState({
    run_id: "DEMO_2026", period_end: "2026-06-30",
    overall: 250000, performance: 175000, currency: "USD",
    system: "sap", amount_column: "DMBTR", currency_column: "WAERS",
    column_map: { posting_date: "BUDAT", document_date: "BLDAT", account: "HKONT",
                  username: "UNAME", description: "SGTXT", source_doc: "BELNR",
                  entry_ref: "BELNR", entry_created_date: "CPUDT" },
    high_risk_users: [], max_universe_size: 200, review_mode: "human",
  });
  const [autodetecting, setAutodetecting] = useState(false);
  const [detection, setDetection] = useState(null);
  const autoDetect = async () => {
    if (!file) { setMsg({ ok: false, err: "Choose a CSV extract first to auto-detect." }); return; }
    setAutodetecting(true); setMsg(null);
    try {
      const d = await api.autodetect(file);
      setConfig(c => ({
        ...c, system: d.system || c.system,
        amount_column: d.amount_column || c.amount_column,
        currency_column: d.currency_column || c.currency_column,
        column_map: {
          posting_date: d.column_map.posting_date || c.column_map.posting_date,
          document_date: d.column_map.document_date || c.column_map.document_date,
          account: d.column_map.account || c.column_map.account,
          username: d.column_map.username || c.column_map.username,
          description: d.column_map.description || c.column_map.description,
          source_doc: d.column_map.source_doc || c.column_map.source_doc,
          entry_ref: d.column_map.entry_ref || c.column_map.entry_ref,
          entry_created_date: d.column_map.entry_created_date || c.column_map.entry_created_date,
          entry_type: d.column_map.entry_type || c.column_map.entry_type,
        },
      }));
      setDetection(d);
    } catch (e) { setMsg({ ok: false, err: e.message }); }
    setAutodetecting(false);
  };
  const yamlOf = () => {
    const c = config, m = c.column_map;
    const map = Object.entries(m).filter(([, v]) => v).map(([k, v]) => `    ${k}: ${v}`).join("\n");
    const users = c.high_risk_users.length ? `\nrisk_context:\n  high_risk_users: [${c.high_risk_users.join(", ")}]` : "";
    return `run_id: ${c.run_id}
period_end: '${c.period_end}'
materiality: {overall: ${c.overall}, performance: ${c.performance}, currency: ${c.currency}}
source:
  system: ${c.system}
  amount_column: ${c.amount_column}
  currency_column: ${c.currency_column}
  column_map:
${map}${users}
review:
  max_universe_size: ${c.max_universe_size}
  overflow_policy: stratify
  pack_size: 20
  mode: ${c.review_mode}
llm_privacy: {mode: zero_retention, pii_scrubbing: true}
reviewer: {name: jdoe}
`;
  };
  const start = async () => {
    if (!file) { setMsg({ ok: false, err: "Choose a CSV extract first." }); return; }
    if (!config.run_id.trim()) { setMsg({ ok: false, err: "Enter a run ID." }); return; }
    setBusy(true); setMsg(null);
    try {
      const r = await api.createEngagement(yamlOf(), file);
      if (r.detail) throw new Error(r.detail);
      setMsg({ ok: true, text: `Started ${r.started} — pipeline running.` });
      onStarted(r.started);
    } catch (e) { setMsg({ ok: false, err: e.message }); }
    setBusy(false);
  };
  return (
    <div style={card}>
      <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                   color: SLATE, margin: "0 0 6px" }}>New engagement</h2>
      <p style={{ color: SLATE, fontSize: 12.5, margin: "0 0 18px" }}>
        Upload a journal-entry extract (CSV) and configure the engagement. The
        pipeline stages are verified as it runs.</p>
      <label style={label}>Journal-entry extract (CSV)</label>
      <input type="file" accept=".csv" onChange={e => { setFile(e.target.files[0]); setMsg(null); }}
             style={{ fontSize: 13, marginBottom: 14 }} />
      <div style={{ marginBottom: 14 }}>
        <span style={{ color: FAINT, fontSize: 11.5 }}>
          {file ? `Selected: ${file.name}` : "No file selected"}</span>
      </div>
      <ConfigForm config={config} setConfig={setConfig} onAutodetect={autoDetect}
                  autodetecting={autodetecting} detection={detection} />
      {msg && <p style={{ fontSize: 12.5, color: msg.ok ? OI_GREEN : OI_VERM }}>{msg.ok ? msg.text : msg.err}</p>}
      <button style={btn} onClick={start} disabled={busy}>▶ Start run</button>
    </div>
  );
}

// ————————————————————————————— ENGAGEMENTS (list)
function Engagements({ runs, onSelect, selected, refresh, onNew }) {
  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                    marginBottom: 8 }}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: 0 }}>Engagements</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={btnGhost} onClick={refresh}>↻ Refresh</button>
          {onNew && <button style={btn} onClick={onNew}>+ New</button>}
        </div>
      </div>
      {runs.length === 0 && <p style={{ color: SLATE, fontSize: 13 }}>No runs yet.</p>}
      {runs.map(r => (
        <div key={r.run_id} onClick={() => onSelect(r.run_id)} style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "11px 6px", borderBottom: `1px solid ${HAIR}`, cursor: "pointer",
          background: selected === r.run_id ? PAPER : "transparent",
          borderRadius: selected === r.run_id ? 6 : 0 }}>
          <div>
            <b className="mono" style={{ fontSize: 13.5 }}>{r.run_id}</b>
            <div style={{ fontSize: 11.5, color: SLATE }}>phase {r.phase || "—"}</div>
          </div>
          {chip(tup(r.status), {
            background: r.status === "finalized" ? "#fff" : "#fdf3e3",
            color: r.status === "finalized" ? INK : AMBER,
            border: `1.2px solid ${r.status === "finalized" ? INK : AMBER}` })}
        </div>
      ))}
    </div>
  );
}

// ————————————————————————————— MONITOR (events + metrics)
function Monitor({ runId }) {
  const [m, setM] = useState(null);
  const [d, setD] = useState(null);
  useEffect(() => {
    api.metrics(runId).then(setM).catch(() => {});
    api.runDetail(runId).then(setD).catch(() => {});
  }, [runId]);
  if (!m) return <div style={card}>Loading metrics…</div>;
  return (
    <div>
      <div style={card}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: "0 0 12px" }}>Run metrics</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {[["Lines", m.population], ["Flagged docs", m.flagged_docs],
            ["Universe", m.universe_selected], ["Status", m.status]].map(([l, v]) => (
            <div key={l} style={{ padding: 14, background: PAPER, borderRadius: 8 }}>
              <div style={{ fontSize: 22, fontWeight: 800 }}>{v}</div>
              <div style={{ fontSize: 10.5, color: SLATE, textTransform: "uppercase",
                            letterSpacing: 1 }}>{l}</div>
            </div>))}
        </div>
      </div>
      <div style={card}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: "0 0 12px" }}>Rule outcomes</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead><tr style={{ textAlign: "left", color: SLATE, fontSize: 10.5,
                             textTransform: "uppercase", letterSpacing: 0.6 }}>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}` }}>rule</th>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}`, textAlign: "right" }}>flags</th>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}` }}>share</th>
          </tr></thead>
          <tbody>
            {Object.entries(m.rule_counts).map(([k, v]) => {
              const pct = m.flagged_docs ? (v / m.flagged_docs * 100).toFixed(1) : 0;
              return (
                <tr key={k}>
                  <td style={{ padding: "7px 9px", borderBottom: `1px solid ${HAIR}`, fontFamily: mono }}>{k}</td>
                  <td style={{ padding: "7px 9px", borderBottom: `1px solid ${HAIR}`, textAlign: "right",
                               fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{v.toLocaleString()}</td>
                  <td style={{ padding: "7px 9px", borderBottom: `1px solid ${HAIR}` }}>
                    <div style={{ background: HAIR, borderRadius: 4, height: 8, width: "100%" }}>
                      <div style={{ background: INK, height: 8, borderRadius: 4, width: `${Math.min(100, pct)}%` }} />
                    </div>
                  </td>
                </tr>); })}
          </tbody>
        </table>
      </div>
      <div style={card}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: "0 0 12px" }}>Audit events</h2>
        {(d?.events || []).map((e, i) => (
          <div key={i} style={{ padding: "6px 0", borderBottom: `1px solid ${HAIR}`,
                                fontSize: 12.5, display: "flex", gap: 8 }}>
            <span style={{ color: FAINT, fontFamily: mono, fontSize: 11 }}>
              {new Date(e.ts).toLocaleString()}</span>
            <b style={{ color: INK }}>{e.kind}</b>
            <span style={{ color: SLATE }}>{e.detail}</span>
          </div>))}
      </div>
    </div>
  );
}

// ————————————————————————————— REVIEW (queue + decisions)
function Review({ runId }) {
  const [u, setU] = useState(null);
  const [reviewer, setReviewer] = useState("jdoe");
  const [msg, setMsg] = useState("");
  const [reasoning, setReasoning] = useState({ ref: null, decision: null, text: "" });
  const load = () => api.universe(runId).then(setU).catch(e => setMsg(e.message));
  useEffect(() => { load(); }, [runId]);
  if (!u) return <div style={card}>Loading review queue…</div>;
  const decided = u.entries.filter(e => e.decision !== "pending");
  const pending = u.entries.filter(e => e.decision === "pending");
  const ask = (ref, decision) => setReasoning({ ref, decision, text: "" });
  const confirm = async () => {
    const { ref, decision, text } = reasoning;
    if (!text.trim()) { setMsg("A reason is required."); return; }
    await api.saveDecisions(runId, reviewer, [{ entry_ref: ref, decision, reason: text }]);
    setReasoning({ ref: null, decision: null, text: "" });
    setMsg(`Recorded ${decision} for ${ref} (hash-chained)`);
    load();
  };
  const finalize = async () => {
    setMsg("Finalizing — running triage/narrative if missing…");
    try {
      const r = await api.finalize(runId);
      if (r.status === "finalized") {
        setMsg(`✔ Finalized — ${r.artifacts.join(", ")}`);
      } else {
        setMsg(`⏳ Not finalized — gates: ` +
          `${r.gates && r.gates.g1_review ? "review✓" : "review✗"} ` +
          `${r.gates && r.gates.g2_procedures ? "procedures✓" : "procedures✗"} ` +
          `${r.gates && r.gates.g3_citations ? "citations✓" : "citations✗"} ` +
          `${r.gates && r.gates.g4_limitations ? "limitations✓" : "limitations✗"}. ` +
          `(${(r.gates && r.gates.problems || []).slice(0, 2).join("; ")})`);
      }
    } catch (e) { setMsg(`✖ ${e.message}`); }
    load();
  };
  return (
    <div>
      <div style={{ ...card, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                       color: SLATE, margin: 0 }}>Review queue</h2>
          <p style={{ fontSize: 12.5, color: SLATE, margin: "4px 0 0" }}>
            {decided.length} decided · {pending.length} pending of {u.selected}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...input, width: 120 }} value={reviewer}
                 onChange={e => setReviewer(e.target.value)} />
          <button style={btn} onClick={finalize}>🏁 Finalize</button>
        </div>
      </div>
      {msg && <p style={{ fontSize: 12.5, color: SLATE, margin: "0 0 10px" }}>{msg}</p>}
      {reasoning.ref && (
        <div style={{ ...card, border: `1.5px solid ${AMBER}`, marginBottom: 14 }}>
          <label style={label}>Reason for {reasoning.decision} on {reasoning.ref}</label>
          <textarea style={{ ...input, fontFamily: mono, minHeight: 80, fontSize: 12.5 }}
                    autoFocus value={reasoning.text}
                    onChange={e => { setReasoning({ ...reasoning, text: e.target.value }); setMsg(""); }}
                    onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) confirm(); }} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button style={btn} onClick={confirm}>✔ Confirm</button>
            <button style={btnGhost} onClick={() => setReasoning({ ref: null, decision: null, text: "" })}>
              Cancel</button>
            <span style={{ fontSize: 11, color: FAINT, alignSelf: "center" }}>Ctrl/Cmd+Enter to submit</span>
          </div>
        </div>)}
      <div style={card}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead><tr style={{ textAlign: "left", color: SLATE, fontSize: 10.5,
                             textTransform: "uppercase", letterSpacing: 0.6 }}>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}` }}>entry</th>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}` }}>rules</th>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}`, textAlign: "right" }}>amount</th>
            <th style={{ padding: "7px 9px", borderBottom: `2px solid ${HAIR}` }}>decision</th>
            <th></th>
          </tr></thead>
          <tbody>
            {u.entries.slice(0, 60).map(e => (
              <tr key={e.entry_ref}>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`, fontFamily: mono, fontWeight: 700 }}>
                  {e.entry_ref}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}` }}>{e.rules_hit}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`, textAlign: "right",
                             fontVariantNumeric: "tabular-nums" }}>
                  {e.abs_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}` }}>
                  {chip(e.decision === "pending" ? "pending" : e.decision, {
                    background: e.decision === "inspect" ? "#fdf3e3" :
                                e.decision === "accept" ? "#fff" : "#eef0f2",
                    color: e.decision === "inspect" ? AMBER : SLATE,
                    border: e.decision === "accept" ? `1.2px solid ${HAIR}` : "none" })}
                </td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`, whiteSpace: "nowrap" }}>
                  {e.decision === "pending" ? (
                    <>
                      <button onClick={() => ask(e.entry_ref, "inspect")}
                              style={{ ...btn, padding: "4px 9px", fontSize: 11.5 }}>inspect</button>{" "}
                      <button onClick={() => ask(e.entry_ref, "accept")}
                              style={{ ...btnGhost, padding: "4px 9px", fontSize: 11.5 }}>accept</button>
                    </>) : <span style={{ color: OI_GREEN }}>✓</span>}
                </td>
              </tr>))}
          </tbody>
        </table>
        {u.entries.length > 60 && <p style={{ color: SLATE, fontSize: 11.5, marginTop: 8 }}>
          Showing first 60 of {u.entries.length}.</p>}
      </div>
    </div>
  );
}

// ————————————————————————————— REPORT (deliverables + metrics snapshot)
function Report({ runId }) {
  const [m, setM] = useState(null);
  const [dl, setDl] = useState("");
  useEffect(() => { api.metrics(runId).then(setM).catch(() => {}); }, [runId]);
  const arts = ["report.pdf", "report.html", "workpaper.xlsx", "flagged_entries.xlsx"];
  return (
    <div>
      <div style={card}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: "0 0 14px" }}>Engagement summary</h2>
        {m && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10 }}>
            {[["Lines", m.population], ["Flagged", m.flagged_docs], ["Universe", m.universe_selected],
              ["Inspect", m.decisions.inspect], ["Benford MAD", m.benford?.mad?.toFixed(4)]].map(([l, v]) => (
              <div key={l} style={{ padding: 12, background: PAPER, borderRadius: 8 }}>
                <div style={{ fontSize: 18, fontWeight: 800 }}>{v ?? "—"}</div>
                <div style={{ fontSize: 10, color: SLATE, textTransform: "uppercase", letterSpacing: 1 }}>{l}</div>
              </div>))}
          </div>)}
      </div>
      <div style={card}>
        <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                     color: SLATE, margin: "0 0 14px" }}>Deliverables</h2>
        {arts.map(n => (
          <button key={n} onClick={async () => {
            try { await api.download(runId, n); }
            catch (e) { setDl(e.message); }
          }}
            style={{ display: "flex", justifyContent: "space-between", width: "100%",
                     padding: "10px 0", fontSize: 13, color: INK, cursor: "pointer",
                     border: "none", borderBottom: `1px solid ${HAIR}`, background: "transparent" }}>
            <span>⬇️ {n}</span><span style={{ color: SLATE }}>download</span>
          </button>))}
        {dl && <p style={{ fontSize: 12, color: OI_VERM, marginTop: 8 }}>{dl}</p>}
      </div>
      {m?.benford?.mad != null && (
        <div style={card}>
          <h2 style={{ fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase",
                       color: SLATE, margin: "0 0 8px" }}>Benford first-digit distribution</h2>
          <p style={{ fontSize: 12, color: SLATE, margin: "0 0 10px" }}>
            MAD {m.benford.mad.toFixed(4)} — {m.benford.nigrini_assessment || "—"} (informational, amendment C2).</p>
          <BenfordChart counts={m.benford.counts} />
        </div>)}
    </div>
  );
}
function BenfordChart({ counts }) {
  const digits = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
  const observed = digits.map(d => (counts || {})[Number(d)] || 0);
  const total = observed.reduce((a, b) => a + b, 0) || 1;
  const max = Math.max(...observed.map(o => o / total)) || 1;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 160 }}>
      {digits.map((d, i) => {
        const o = observed[i] / total;
        return (
          <div key={d} style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 10, color: SLATE, marginBottom: 2 }}>
              {(o * 100).toFixed(1)}%</div>
            <div style={{ background: INK, height: (o / max) * 110, borderRadius: "3px 3px 0 0" }} />
            <div style={{ fontSize: 11, fontWeight: 700, marginTop: 4 }}>{d}</div>
          </div>); })}
    </div>
  );
}

// ————————————————————————————— APP (nav shell)
const PAGES = [
  { id: "engage", label: "Engagements" },
  { id: "new", label: "New engagement" },
  { id: "monitor", label: "Monitor" },
  { id: "review", label: "Review" },
  { id: "report", label: "Report" },
  { id: "configure", label: "Configure" },
];
function AppInner({ onSignOut }) {
  const [runs, setRuns] = useState(null);
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState("engage");
  const refresh = () => api.runs().then(r => { setRuns(r.runs); return r.runs; })
    .catch(() => { sessionStorage.removeItem("jeagent_key"); onSignOut(); });
  if (!runs) refresh();
  const hasRun = !!selected;
  const opened = (id) => { setSelected(id); setPage("monitor"); };
  return (
    <div style={{ background: PAPER, minHeight: "100vh" }}>
      <div style={{ background: INK, color: "#fff", padding: "14px 0" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "0 22px",
                      display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 10, letterSpacing: 2.6, textTransform: "uppercase",
                          color: "#aeb6bf" }}>Journal Entry Testing · ISA 240 / AS 2401</div>
            <div style={{ fontSize: 19, fontWeight: 800 }}>JE Agent Console</div>
          </div>
          <button style={{ ...btn, background: "transparent", color: "#fff",
                           border: `1.2px solid #4b5563` }} onClick={onSignOut}>Sign out</button>
        </div>
      </div>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "0 22px" }}>
        <nav style={{ display: "flex", gap: 4, borderBottom: `2px solid ${INK}`, marginBottom: 18 }}>
          {PAGES.map(p => (
            <button key={p.id} onClick={() => setPage(p.id)} style={{
              background: "none", border: "none", padding: "12px 16px 10px", cursor: "pointer",
              fontWeight: 700, fontSize: 13, color: page === p.id ? INK : SLATE,
              borderBottom: page === p.id ? `3px solid ${AMBER}` : "3px solid transparent" }}>
              {p.label}</button>))}
        </nav>
        {page === "configure" && <Configure />}
        {page === "new" && <NewEngagement onStarted={opened} />}
        {(page === "engage" && !hasRun) && (
          <Engagements runs={runs || []} selected={selected} onSelect={setSelected}
                       refresh={refresh} onNew={() => setPage("new")} />)}
        {(page === "engage" && hasRun) && (
          <Engagements runs={runs || []} selected={selected} onSelect={opened}
                       refresh={refresh} onNew={() => setPage("new")} />)}
        {hasRun && page === "monitor" && <Monitor runId={selected} />}
        {hasRun && page === "review" && <Review runId={selected} />}
        {hasRun && page === "report" && <Report runId={selected} />}
        {hasRun && page !== "monitor" && page !== "review" && page !== "report" &&
         page !== "configure" && <Engagements runs={runs || []} selected={selected}
                              onSelect={setSelected} refresh={refresh} />}
      </div>
    </div>
  );
}
export default function App() {
  const [authed, setAuthed] = useState(!!sessionStorage.getItem("jeagent_key"));
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;
  return <AppInner onSignOut={() => { sessionStorage.clear(); setAuthed(false); }} />;
}
