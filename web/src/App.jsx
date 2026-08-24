import { useEffect, useState } from "react";
import { api } from "./api";

const INK = "#111827", SLATE = "#4b5563", HAIR = "#e5e7eb", PAPER = "#f6f7f8",
      CARD = "#fff", AMBER = "#b45309";

const btn = {
  background: INK, color: "#fff", border: "none", borderRadius: 7,
  padding: "9px 18px", fontSize: 13, fontWeight: 650, cursor: "pointer",
};
const input = {
  border: `1px solid ${HAIR}`, borderRadius: 7, padding: "9px 12px",
  fontSize: 13, width: "100%", boxSizing: "border-box",
};
const card = {
  background: CARD, border: `1px solid ${HAIR}`, borderRadius: 8,
  padding: 20, marginBottom: 14,
};

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
    try {
      await api.runs();
      onLogin();
    } catch (e) {
      setErr(e.message);
      sessionStorage.removeItem("jeagent_key");
    }
  };
  return (
    <div style={{ maxWidth: 380, margin: "90px auto" }}>
      <div style={{ fontSize: 11, letterSpacing: 2.4, textTransform: "uppercase",
                    color: SLATE, marginBottom: 8 }}>
        JE Agent · ISA 240
      </div>
      <h1 style={{ fontSize: 24, margin: "0 0 18px" }}>Sign in</h1>
      <input style={input} type="password" placeholder="API key"
             value={key} onChange={e => setKey(e.target.value)}
             onKeyDown={e => e.key === "Enter" && tryKey()} />
      {err && <p style={{ color: "#b91c1c", fontSize: 12.5 }}>{err}</p>}
      <button style={{ ...btn, marginTop: 14, width: "100%" }} onClick={tryKey}>
        Continue
      </button>
      {sso && (
        <p style={{ color: SLATE, fontSize: 11.5, marginTop: 16 }}>
          Corporate single sign-on (Microsoft Entra ID) is enabled on this server.
        </p>
      )}
    </div>
  );
}

function RunList({ runs, onSelect, selected }) {
  return (
    <div style={card}>
      <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: 1.2,
                   color: SLATE, margin: "0 0 12px" }}>Engagements</h2>
      {runs.length === 0 && <p style={{ color: SLATE, fontSize: 13 }}>No runs yet.</p>}
      {runs.map(r => (
        <div key={r.run_id} onClick={() => onSelect(r.run_id)}
             style={{
               display: "flex", justifyContent: "space-between", padding: "10px 4px",
               borderBottom: `1px solid ${HAIR}`, cursor: "pointer",
               background: selected === r.run_id ? PAPER : "transparent",
               borderRadius: selected === r.run_id ? 6 : 0,
             }}>
          <b style={{ fontSize: 13.5 }}>{r.run_id}</b>
          <span className="chip" style={{
            fontSize: 10.5, fontWeight: 700, padding: "2px 10px", borderRadius: 999,
            background: r.status === "finalized" ? "#fff" : "#fdf3e3",
            color: r.status === "finalized" ? INK : AMBER,
            border: `1.2px solid ${r.status === "finalized" ? INK : AMBER}`,
          }}>{r.status}</span>
        </div>
      ))}
    </div>
  );
}

function RunDetail({ runId }) {
  const [detail, setDetail] = useState(null);
  const [universe, setUniverse] = useState(null);
  const [reviewer, setReviewer] = useState("jdoe");
  const [msg, setMsg] = useState("");

  const loadAll = async () => {
    setDetail(await api.runDetail(runId));
    setUniverse(await api.universe(runId));
  };
  if (!detail) loadAll().catch(e => setMsg(e.message));

  const decide = async (ref, decision) => {
    const reason = prompt(`Reason for ${decision} on ${ref}:`) || "";
    await api.saveDecisions(runId, reviewer,
      [{ entry_ref: ref, decision, reason }]);
    setMsg(`Recorded ${decision} for ${ref} (hash-chained)`);
    setUniverse(await api.universe(runId));
  };

  const finalize = async () => {
    const r = await api.finalize(runId);
    setMsg(r.finalized
      ? `✔ Finalized — artifacts: ${r.artifacts.join(", ")}`
      : `Gates blocked: ${(r.problems || []).join(" | ")}`);
    setDetail(await api.runDetail(runId));
  };

  if (!detail) return <div style={card}>Loading…</div>;
  const decided = universe?.entries.filter(e => e.decision !== "pending") || [];
  const pending = universe?.entries.filter(e => e.decision === "pending") || [];

  return (
    <div>
      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h1 style={{ fontSize: 20, margin: 0 }}>{runId}</h1>
            <span style={{ color: SLATE, fontSize: 12.5 }}>
              status {detail.status} · phase {detail.phase} · lock{" "}
              {detail.lock_stale ? "STALE" : detail.locked ? "held" : "free"}
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input style={{ ...input, width: 120 }} value={reviewer}
                   onChange={e => setReviewer(e.target.value)} />
            <button style={btn} onClick={finalize}>🏁 Finalize</button>
          </div>
        </div>
        {msg && <p style={{ marginTop: 12, fontSize: 12.5, color: SLATE }}>{msg}</p>}
      </div>

      <div style={card}>
        <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: 1.2,
                     color: SLATE, margin: "0 0 10px" }}>Review queue</h2>
        <p style={{ fontSize: 12.5, color: SLATE, margin: "0 0 10px" }}>
          {decided.length} decided · {pending.length} pending of {universe.selected}
        </p>
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
            {(universe?.entries || []).slice(0, 50).map(e => (
              <tr key={e.entry_ref}>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`,
                             fontFamily: "Consolas, monospace", fontWeight: 700 }}>
                  {e.entry_ref}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}` }}>
                  {e.rules_hit}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`,
                             textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {e.abs_amount.toLocaleString(undefined,
                    { maximumFractionDigits: 0 })}</td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}` }}>
                  <span className="chip" style={{
                    fontSize: 10.5, fontWeight: 700, padding: "2px 10px",
                    borderRadius: 999,
                    ...(e.decision === "inspect"
                        ? { background: "#fdf3e3", color: AMBER }
                        : e.decision === "accept"
                          ? { background: "#fff", color: SLATE, border: `1.2px solid ${HAIR}` }
                          : { background: "#eef0f2", color: SLATE }),
                  }}>{e.decision}</span></td>
                <td style={{ padding: "6px 9px", borderBottom: `1px solid ${HAIR}`,
                             whiteSpace: "nowrap" }}>
                  {e.decision === "pending" ? (
                    <>
                      <button style={{ ...btn, padding: "4px 10px", fontSize: 11.5 }}
                              onClick={() => decide(e.entry_ref, "inspect")}>inspect</button>{" "}
                      <button style={{
                        ...btn, padding: "4px 10px", fontSize: 11.5,
                        background: "#fff", color: INK,
                        border: `1.2px solid ${INK}`,
                      }} onClick={() => decide(e.entry_ref, "accept")}>accept</button>
                    </>
                  ) : <span style={{ color: SLATE, fontSize: 11.5 }}>✓</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(universe?.entries.length || 0) > 50 && (
          <p style={{ color: SLATE, fontSize: 11.5, marginTop: 8 }}>
            Showing first 50 of {universe.entries.length}.</p>
        )}
      </div>

      <div style={card}>
        <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: 1.2,
                     color: SLATE, margin: "0 0 10px" }}>Deliverables</h2>
        {["report.pdf", "report.html", "workpaper.xlsx", "flagged_entries.xlsx"].map(n => (
          <a key={n} href={api.artifactUrl(runId, n)} target="_blank"
             rel="noreferrer"
             style={{ display: "block", padding: "8px 0", fontSize: 13,
                      color: INK, textDecoration: "none",
                      borderBottom: `1px solid ${HAIR}` }}>
              ⬇️ {n}</a>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!sessionStorage.getItem("jeagent_key"));
  const [runs, setRuns] = useState(null);
  const [selected, setSelected] = useState(null);

  const refresh = () => api.runs().then(r => setRuns(r.runs)).catch(() => {
    sessionStorage.removeItem("jeagent_key");
    setAuthed(false);
  });
  if (authed && !runs) refresh();

  if (!authed) return <Login onLogin={() => { setAuthed(true); refresh(); }} />;

  return (
    <div style={{ background: PAPER, minHeight: "100vh" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "26px 22px" }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "flex-end", paddingBottom: 14,
                      borderBottom: `3px solid ${INK}`, marginBottom: 18 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 2.4,
                          textTransform: "uppercase", color: SLATE }}>
              Journal Entry Testing · ISA 240 / AS 2401</div>
            <div style={{ fontSize: 21, fontWeight: 800 }}>JE Agent Console</div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button style={{ ...btn, background: "#fff", color: INK,
                             border: `1.2px solid ${INK}` }} onClick={refresh}>
              ↻ Refresh</button>
            <button style={{ ...btn, background: "#fff", color: SLATE,
                             border: `1.2px solid ${HAIR}` }}
                    onClick={() => { sessionStorage.clear(); setAuthed(false); }}>
              Sign out</button>
          </div>
        </div>
        <RunList runs={runs || []} selected={selected}
                 onSelect={id => setSelected(id)} />
        {selected && <RunDetail key={selected} runId={selected} />}
      </div>
    </div>
  );
}
