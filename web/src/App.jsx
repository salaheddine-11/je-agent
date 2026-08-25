import { Fragment, useEffect, useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { Toaster, toast } from "sonner";
import { api, BASE } from "./api";
import { STRINGS } from "./i18n";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

gsap.registerPlugin(useGSAP);

/* ————————————————————————————————————————————————————————————————
   JE Agent console v1.1 — warm-paper ledger design
   Palette: ink #1f1e1c · paper #faf9f7 · amber accent #b45309
   Motion: GSAP, subtle, reduced-motion aware
   ————————————————————————————————————————— */

const t0 = (s) => s; // translation passthrough placeholder

function App() {
  const [key, setKey] = useState(sessionStorage.getItem("jeagent_key") || "");
  return key ? (
    <AppInner onSignOut={() => { sessionStorage.removeItem("jeagent_key"); setKey(""); }} />
  ) : (
    <Login onOk={setKey} />
  );
}

function Login({ onOk }) {
  const [k, setK] = useState("");
  const [err, setErr] = useState(null);
  const root = useRef(null);
  useGSAP(() => {
    gsap.from(".login-card", { y: 18, autoAlpha: 0, duration: 0.55, ease: "power3.out" });
    gsap.from(".login-rule", { scaleX: 0, transformOrigin: "left center", duration: 0.7, ease: "power2.inOut", delay: 0.15 });
  }, { scope: root });

  const submit = async () => {
    try {
      const r = await fetch(`${BASE}/api/runs`, { headers: { "X-API-Key": k } });
      if (!r.ok) throw new Error("invalid");
      sessionStorage.setItem("jeagent_key", k);
      onOk(k);
    } catch { setErr(true); }
  };
  return (
    <div ref={root} className="min-h-screen bg-paper flex items-center justify-center p-6">
      <div className="login-card w-full max-w-sm rounded-2xl border border-hairline bg-card p-8 shadow-[0_4px_24px_rgba(31,30,28,0.06)]">
        <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-ink-faint">Journal Entry Testing</div>
        <h1 className="mt-2 text-[22px] font-bold leading-tight tracking-tight text-ink">JE Agent Console</h1>
        <hr className="login-rule my-5 border-0 h-px bg-amber/70" />
        <Label htmlFor="key" className="text-xs uppercase tracking-wider text-ink-soft">API key</Label>
        <Input id="key" type="password" value={k} onChange={e => setK(e.target.value)}
               onKeyDown={e => e.key === "Enter" && submit()}
               className="mt-1.5 font-mono" placeholder="••••••••" autoFocus />
        {err && <p className="mt-2 text-xs text-red-700">That key didn't work — check and retry.</p>}
        <Button className="mt-5 w-full bg-amber hover:bg-amber/85 text-white" onClick={submit}>Continue</Button>
        <p className="mt-4 text-center text-[11px] text-ink-faint">ISA 240 / AS 2401 · local execution</p>
      </div>
    </div>
  );
}

const PAGES = [
  { id: "engage" }, { id: "new" }, { id: "monitor" }, { id: "review" },
  { id: "report" }, { id: "configure" },
];

function AppInner({ onSignOut }) {
  const [runs, setRuns] = useState(null);
  const [runsLoading, setRunsLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState("engage");
  const [lang, setLang] = useState(() => localStorage.getItem("jeagent_lang") || "en");
  const t = STRINGS[lang];
  const setL = (l) => { localStorage.setItem("jeagent_lang", l); setLang(l); };

  const refresh = () => { setRunsLoading(true);
    return api.runs().then(r => { setRuns(r.runs); setRunsLoading(false); return r.runs; })
    .catch(() => { setRunsLoading(false); sessionStorage.removeItem("jeagent_key"); onSignOut(); }); };
  useEffect(() => { if (!runs) refresh(); }, []);

  const hasRun = !!selected;
  const opened = (id) => { setSelected(id); setPage("monitor"); };

  // page transition
  const mainRef = useRef(null);
  useGSAP(() => {
    gsap.fromTo(mainRef.current, { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.35, ease: "power2.out" });
  }, [page]);

  return (
    <div className="min-h-screen bg-paper text-ink">
      {/* masthead */}
      <header className="border-b border-hairline bg-card">
        <div className="flex items-center justify-between px-7 py-3.5">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-ink-faint">{t.eyebrow}</div>
            <div className="text-lg font-bold tracking-tight">{t.appTitle}</div>
          </div>
          <div className="flex items-center gap-2.5">
            <LangToggle lang={lang} setL={setL} />
            <Button variant="outline" size="sm" onClick={onSignOut}>{t.signOut}</Button>
          </div>
        </div>
        <nav className="flex gap-1 px-7">
          {PAGES.map(p => (
            <button key={p.id} onClick={() => setPage(p.id)}
              className={`relative px-3.5 py-2.5 text-[13px] font-semibold transition-colors
                ${page === p.id ? "text-ink" : "text-ink-faint hover:text-ink-soft"}`}>
              {t.pages[p.id]}
              {page === p.id && <span className="absolute inset-x-2 bottom-0 h-[2.5px] rounded-t bg-amber" />}
            </button>
          ))}
        </nav>
      </header>

      <main ref={mainRef} className="px-7 pb-16 pt-5 space-y-4">
        {page === "configure" && <Configure />}
        {page === "new" && <NewEngagement onStarted={opened} />}
        {(page === "engage") && (
          <Engagements runs={runs || []} runsLoading={runsLoading} selected={selected} t={t}
                       onSelect={(id) => { hasRun ? opened(id) : setSelected(id); }}
                       refresh={refresh} onNew={() => setPage("new")} />)}
        {hasRun && page === "monitor" && <Monitor runId={selected} />}
        {hasRun && page === "review" && <Review runId={selected} />}
        {hasRun && page === "report" && <Report runId={selected} />}
        {!hasRun && ["monitor","review","report"].includes(page) && (
          <Card><CardContent className="py-14 text-center text-sm text-ink-faint">
            Open an engagement first — pick one from Engagements.
          </CardContent></Card>)}
      </main>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}

function LangToggle({ lang, setL }) {
  return (
    <div className="flex overflow-hidden rounded-md border border-hairline">
      {["en","fr"].map(l => (
        <button key={l} onClick={() => setL(l)}
          className={`px-2.5 py-1 text-[11px] font-bold uppercase transition-colors
            ${lang === l ? "bg-ink text-white" : "bg-transparent text-ink-faint hover:text-ink-soft"}`}>
          {l}</button>))}
    </div>
  );
}

function StatusChip({ status }) {
  const fin = status === "finalized";
  if (!status) return <span className="text-[11px] uppercase tracking-wide text-ink-faint">no status</span>;
  return (
    <Badge variant="outline"
      className={fin ? "border-ink/25 bg-transparent text-ink" : "border-amber/40 bg-amber-soft text-amber"}>
      {status.replace(/_/g, " ")}
    </Badge>);
}

// ————————————————————————————— ENGAGEMENTS (dashboard)
function Engagements({ runs, runsLoading, onSelect, selected, refresh, onNew, t }) {
  const grid = useRef(null);
  useGSAP(() => {
    gsap.from(".kpi-card", { y: 12, autoAlpha: 0, duration: 0.45, stagger: 0.06, ease: "power2.out", clearProps: "all" });
  }, { scope: grid, dependencies: [runs.length] });

  const finalized = runs.filter(r => r.status === "finalized").length;
  const awaiting = runs.filter(r => r.status === "awaiting_review").length;
  const lines = runs.reduce((s, r) => s + (r.population || 0), 0);

  return (
    <>
      <div ref={grid} className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[{ l: t.kpi.engagements, v: runs.length }, { l: t.kpi.finalized, v: finalized },
          { l: t.kpi.awaiting, v: awaiting }, { l: t.kpi.lines, v: lines.toLocaleString() }].map(({l, v}) => (
          <Card key={l} className="kpi-card rounded-xl border-hairline shadow-none">
            <CardContent className="px-4 py-3.5">
              <div className="font-mono text-[22px] font-bold tabular-nums leading-none">{v}</div>
              <div className="mt-1.5 text-[10.5px] font-medium uppercase tracking-[0.14em] text-ink-faint">{l}</div>
            </CardContent>
          </Card>))}
      </div>

      <Card className="rounded-xl border-hairline">
        <CardHeader className="flex-row items-center justify-between border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">{t.engagements}</CardTitle>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={refresh}>{t.refresh}</Button>
            <Button size="sm" className="bg-amber text-white hover:bg-amber/85" onClick={onNew}>{t.newBtn}</Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {runsLoading && (
            <div className="space-y-2.5 px-4 py-4">
              {[0,1,2].map(i => <div key={i} className="h-9 animate-pulse rounded-md bg-muted" />)}
            </div>)}
          {!runsLoading && runs.length === 0 && (
            <div className="px-4 py-12 text-center text-sm text-ink-faint">{t.noRuns}</div>)}
          {!runsLoading && runs.map(r => (
            <div key={r.run_id}
              onClick={() => onSelect(r.run_id)}
              className={`group flex cursor-pointer items-center justify-between border-b border-hairline px-4 py-2.5 last:border-0 transition-colors
                ${selected === r.run_id ? "bg-amber/60" : "hover:bg-paper"}`}>
              <div className="min-w-0">
                <div className="truncate font-mono text-[13.5px] font-semibold">{r.run_id}</div>
                <div className="mt-0.5 text-[11px] text-ink-faint">
                  {t.phase} {r.phase || "—"} · {(r.population || 0).toLocaleString()} lines</div>
              </div>
              <div className="ml-3 flex shrink-0 items-center gap-2">
                <StatusChip status={r.status} />
                <button title={t.deleteTitle} onClick={(e) => { e.stopPropagation();
                  if (window.confirm(t.deleteConfirm(r.run_id))) {
                    api.deleteRun(r.run_id).then(() => { refresh(); toast.success(`${r.run_id} deleted`); })
                       .catch(err => toast.error(err.message)); } }}
                  className="rounded px-1.5 py-1 text-ink-faint opacity-60 transition-all hover:text-red-700 group-hover:opacity-100">🗑</button>
              </div>
            </div>))}
        </CardContent>
      </Card>
    </>
  );
}

// ————————————————————————————— MONITOR
function Monitor({ runId }) {
  const [m, setM] = useState(null);
  const [d, setD] = useState(null);
  useEffect(() => {
    api.metrics(runId).then(setM).catch(() => {});
    api.runDetail(runId).then(setD).catch(() => {});
  }, [runId]);
  if (!m) return <Card><CardContent className="py-10 text-center text-sm text-ink-faint">Loading metrics…</CardContent></Card>;
  return (
    <>
      <Card className="rounded-xl border-hairline">
        <CardHeader className="border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Run metrics · {runId}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 pt-4 md:grid-cols-4">
          {[["Lines", m.population], ["Flagged docs", m.flagged_docs],
            ["Universe", m.universe_selected], ["Status", m.status]].map(([l, v]) => (
            <div key={l} className="rounded-lg bg-paper px-4 py-3">
              <div className="font-mono text-[22px] font-bold tabular-nums leading-none">{v}</div>
              <div className="mt-1.5 text-[10.5px] font-medium uppercase tracking-[0.14em] text-ink-faint">{l}</div>
            </div>))}
        </CardContent>
      </Card>

      <Card className="rounded-xl border-hairline">
        <CardHeader className="border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Rule outcomes</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">rule</TableHead>
                <TableHead className="text-right">flags</TableHead>
                <TableHead className="pr-4 w-[45%]">share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(m.rule_counts).map(([k, v]) => {
                const pct = m.flagged_docs ? (v / m.flagged_docs * 100) : 0;
                return (
                  <TableRow key={k}>
                    <TableCell className="pl-4 font-mono text-[12.5px]">{k}</TableCell>
                    <TableCell className="text-right font-mono font-semibold tabular-nums">{v.toLocaleString()}</TableCell>
                    <TableCell className="pr-4">
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-ink transition-all" style={{ width: `${Math.min(100, pct)}%` }} />
                      </div>
                    </TableCell>
                  </TableRow>);
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="rounded-xl border-hairline">
        <CardHeader className="border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Audit events</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {(d?.events || []).map((e, i) => (
            <div key={i} className="flex items-baseline gap-3 border-b border-hairline px-4 py-2 text-[12.5px] last:border-0">
              <span className="font-mono text-[11px] text-ink-faint">{new Date(e.ts).toLocaleString()}</span>
              <b>{e.kind}</b>
              <span className="text-ink-soft">{e.detail}</span>
            </div>))}
          {(!d?.events?.length) && (
            <div className="px-4 py-8 text-center text-sm text-ink-faint">No events recorded yet.</div>)}
        </CardContent>
      </Card>
    </>
  );
}

// ————————————————————————————— REVIEW — the ledger (signature element)
function Review({ runId }) {
  const [u, setU] = useState(null);
  const [reviewer, setReviewer] = useState("jdoe");
  const [reasoning, setReasoning] = useState({ ref: null, decision: null, text: "" });
  const [detail, setDetail] = useState(null);
  const load = () => api.universe(runId).then(setU).catch(e => toast.error(e.message));
  useEffect(() => { load(); }, [runId]);

  const toggle = async ref => {
    if (detail && detail.entry_ref === ref) return setDetail(null);
    try { setDetail({ entry_ref: ref, lines: null, flags: null });
          const d = await api.entryDetail(runId, ref); setDetail(d); }
    catch (e) { toast.error(e.message); setDetail(null); }
  };
  if (!u) return <Card><CardContent className="py-10 text-center text-sm text-ink-faint">Loading review queue…</CardContent></Card>;
  const decided = u.entries.filter(e => e.decision !== "pending").length;
  const pending = u.entries.length - decided;

  const ask = (ref, decision) => setReasoning({ ref, decision, text: "" });
  const confirm = async () => {
    const { ref, decision, text } = reasoning;
    if (!text.trim()) { toast.error("A reason is required."); return; }
    await api.saveDecisions(runId, reviewer, [{ entry_ref: ref, decision, reason: text }]);
    setReasoning({ ref: null, decision: null, text: "" });
    toast.success(`Recorded ${decision} for ${ref} (hash-chained)`);
    load();
  };
  const finalize = async () => {
    toast.loading("Finalizing — running triage/narrative if missing…", { id: "fin" });
    try {
      const r = await api.finalize(runId);
      if (r.status === "finalized") {
        toast.success(`Finalized — ${r.artifacts.join(", ")}`, { id: "fin", duration: 5000 });
      } else {
        const g = r.gates || {};
        toast.warning(
          `Gates — review ${g.g1_review ? "✓" : "✗"} · procedures ${g.g2_procedures ? "✓" : "✗"} · citations ${g.g3_citations ? "✓" : "✗"} · limitations ${g.g4_limitations ? "✓" : "✗"}`,
          { id: "fin", duration: 7000, description: (g.problems || []).slice(0, 2).join("; ") });
      }
    } catch (e) { toast.error(e.message, { id: "fin" }); }
    load();
  };

  return (
    <div className="space-y-3">
      {/* reason slip */}
      {reasoning.ref && (
        <Card className="rounded-xl border-amber/50 shadow-[0_6px_24px_rgba(180,83,9,0.08)]">
          <CardContent className="pt-4">
            <Label className="text-xs uppercase tracking-wider text-ink-soft">
              Reason for {reasoning.decision} on <span className="font-mono">{reasoning.ref}</span></Label>
            <textarea autoFocus value={reasoning.text}
              onChange={e => setReasoning({ ...reasoning, text: e.target.value })}
              onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) confirm(); }}
              className="mt-1.5 min-h-[84px] w-full rounded-md border border-hairline bg-card p-2.5 font-mono text-[12.5px] outline-none focus:border-amber/60" />
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" className="bg-amber text-white hover:bg-amber/85" onClick={confirm}>✔ Confirm</Button>
              <Button size="sm" variant="ghost" onClick={() => setReasoning({ ref: null, decision: null, text: "" })}>Cancel</Button>
              <span className="ml-auto text-[11px] text-ink-faint">Ctrl/Cmd+Enter to submit</span>
            </div>
          </CardContent>
        </Card>)}

      {/* queue header */}
      <Card className="rounded-xl border-hairline">
        <CardHeader className="flex-row items-center justify-between border-b border-hairline py-3.5">
          <div>
            <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Review queue</CardTitle>
            <p className="mt-0.5 text-[12px] text-ink-faint">{decided} decided · {pending} pending of {u.selected}</p>
          </div>
          <div className="flex items-center gap-2">
            <Input value={reviewer} onChange={e => setReviewer(e.target.value)} className="h-7 w-28 font-mono text-xs" />
            <Button size="sm" className="bg-ink text-white hover:bg-ink/85" onClick={finalize}>🏁 Finalize</Button>
          </div>
        </CardHeader>

        {/* THE LEDGER */}
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent border-b-border">
                <TableHead className="pl-4 w-[16%]">entry</TableHead>
                <TableHead className="w-[34%]">rules</TableHead>
                <TableHead className="text-right">amount</TableHead>
                <TableHead>decision</TableHead>
                <TableHead className="pr-4" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {u.entries.slice(0, 60).map((e) => (
                <Fragment key={e.entry_ref}>
                  <TableRow className={`group ${detail?.entry_ref === e.entry_ref ? "bg-paper" : ""}`}>
                    <TableCell className="pl-4">
                      <button onClick={() => toggle(e.entry_ref)}
                        className="font-mono font-bold underline-offset-2 hover:text-amber hover:underline">{e.entry_ref}</button>
                    </TableCell>
                    <TableCell className="font-mono text-[12px] text-ink-soft">{e.rules_hit}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {e.abs_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</TableCell>
                    <TableCell>
                      {e.decision === "inspect" && <Badge className="border-0 bg-amber text-amber hover:bg-amber">inspect</Badge>}
                      {e.decision === "accept" && <Badge variant="outline" className="bg-transparent">accept</Badge>}
                      {e.decision === "pending" && <span className="text-[11px] uppercase tracking-wide text-ink-faint">pending</span>}
                    </TableCell>
                    <TableCell className="pr-4 whitespace-nowrap text-right">
                      {e.decision === "pending" ? (
                        <span className="inline-flex gap-1.5 opacity-80 transition-opacity group-hover:opacity-100">
                          <Button size="xs" className="bg-amber text-white hover:bg-amber/85"
                                  onClick={() => ask(e.entry_ref, "inspect")}>inspect</Button>
                          <Button size="xs" variant="outline"
                                  onClick={() => ask(e.entry_ref, "accept")}>accept</Button>
                        </span>
                      ) : <span className="text-emerald-700">✓</span>}
                    </TableCell>
                  </TableRow>

                  {detail && detail.entry_ref === e.entry_ref && (
                    <TableRow key={`${e.entry_ref}-d`} className="hover:bg-paper">
                      <TableCell colSpan={5} className="border-l-2 border-amber/40 bg-paper px-6 pb-4">
                        {detail.lines ? (
                          <div className="pt-1 text-[12px]">
                            <div className={`mb-2 text-[11px] ${Object.keys(detail.flags || {}).length ? "font-semibold text-amber" : "text-ink-faint"}`}>
                              {Object.keys(detail.flags || {}).length
                                ? `Rules hit: ${Object.keys(detail.flags).join(" · ")}`
                                : "No rule flags reported"}
                            </div>
                            <table className="w-full text-[11.5px]">
                              <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-ink-faint">
                                  <th className="py-1 pr-3 text-left font-medium">ln</th>
                                  <th className="py-1 pr-3 text-left font-medium">date</th>
                                  <th className="py-1 pr-3 text-left font-medium">account</th>
                                  <th className="py-1 pr-3 text-left font-medium">user</th>
                                  <th className="py-1 pr-3 text-right font-medium">amount</th>
                                  <th className="py-1 text-left font-medium">description</th>
                                </tr>
                              </thead>
                              <tbody>
                                {detail.lines.map(l => (
                                  <tr key={l.line_no} className="border-t border-hairline">
                                    <td className="py-1.5 pr-3 font-mono">{l.line_no}</td>
                                    <td className="py-1.5 pr-3 font-mono">{l.posting_date}</td>
                                    <td className="py-1.5 pr-3 font-mono">{l.account}</td>
                                    <td className="py-1.5 pr-3">{l.username}</td>
                                    <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                                      {Number(l.amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                                    <td className="py-1.5 text-ink-soft">{l.description || "—"}</td>
                                  </tr>))}
                              </tbody>
                            </table>
                          </div>
                        ) : <div className="py-2 text-[11.5px] text-ink-faint">Loading lines…</div>}
                      </TableCell>
                    </TableRow>)}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          {u.entries.length > 60 && (
            <p className="border-t border-hairline px-4 py-2.5 text-[11.5px] text-ink-faint">
              Showing first 60 of {u.entries.length}.</p>)}
        </CardContent>
      </Card>
    </div>
  );
}

// ————————————————————————————— REPORT
function Report({ runId }) {
  const [m, setM] = useState(null);
  useEffect(() => { api.metrics(runId).then(setM).catch(() => {}); }, [runId]);
  const arts = ["report.pdf", "report.html", "workpaper.xlsx", "flagged_entries.xlsx"];
  return (
    <>
      <Card className="rounded-xl border-hairline">
        <CardHeader className="border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Engagement summary</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 pt-4 md:grid-cols-5">
          {[["Lines", m?.population], ["Flagged", m?.flagged_docs], ["Universe", m?.universe_selected],
            ["Inspect", m?.decisions?.inspect], ["Benford MAD", m?.benford?.mad?.toFixed(4)]].map(([l, v]) => (
            <div key={l} className="rounded-lg bg-paper px-4 py-3">
              <div className="font-mono text-lg font-bold tabular-nums leading-none">{v ?? "—"}</div>
              <div className="mt-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-ink-faint">{l}</div>
            </div>))}
        </CardContent>
      </Card>

      <Card className="rounded-xl border-hairline">
        <CardHeader className="border-b border-hairline py-3.5">
          <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Deliverables</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {arts.map(n => (
            <div key={n} className="group flex items-center justify-between border-b border-hairline px-4 py-2.5 last:border-0">
              <span className="font-mono text-[13px]">⬇ {n}</span>
              <span className="flex gap-2 opacity-80 transition-opacity group-hover:opacity-100">
                {(n === "report.pdf" || n === "report.html") && (
                  <Button size="xs" variant="secondary" onClick={async () => {
                    try { window.open(await api.artifactUrl(runId, n), "_blank"); }
                    catch (e) { toast.error(e.message); }}}>view</Button>)}
                <Button size="xs" variant="outline" onClick={async () => {
                  try { await api.download(runId, n); toast.success(`${n} downloaded`); }
                  catch (e) { toast.error(e.message); }}}>download</Button>
              </span>
            </div>))}
        </CardContent>
      </Card>

      {m?.benford?.mad != null && (
        <Card className="rounded-xl border-hairline">
          <CardHeader className="border-b border-hairline py-3.5">
            <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Benford first-digit distribution</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <p className="mb-3 text-[12px] text-ink-soft">
              MAD {m.benford.mad.toFixed(4)} — {m.benford.nigrini_assessment || "—"} (informational, amendment C2).</p>
            <BenfordChart counts={m.benford.counts} />
          </CardContent>
        </Card>)}
    </>
  );
}

function BenfordChart({ counts }) {
  const digits = ["1","2","3","4","5","6","7","8","9"];
  const observed = digits.map(d => (counts || {})[Number(d)] || 0);
  const total = observed.reduce((a, b) => a + b, 0) || 1;
  const max = Math.max(...observed.map(o => o / total)) || 1;
  const barsRef = useRef(null);
  useGSAP(() => {
    gsap.from(".ben-bar", { scaleY: 0, transformOrigin: "bottom", duration: 0.6, stagger: 0.05, ease: "power3.out",
                            clearProps: "transform" });
  }, { scope: barsRef });
  return (
    <div ref={barsRef} className="flex h-40 items-end gap-2">
      {digits.map((d, i) => {
        const o = observed[i] / total;
        return (
          <div key={d} className="flex-1 text-center">
            <div className="mb-1 text-[10px] text-ink-soft">{(o * 100).toFixed(1)}%</div>
            <div className="ben-bar mx-auto w-full rounded-t-sm bg-ink" style={{ height: (o / max) * 110 }} />
            <div className="mt-1.5 text-[11px] font-bold">{d}</div>
          </div>);
      })}
    </div>
  );
}

// ————————————————————————————— NEW ENGAGEMENT + CONFIG FORM
function NewEngagement({ onStarted }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState({
    run_id: "DEMO_2026", period_end: "2026-06-30",
    overall: 250000, performance: 175000, currency: "USD",
    system: "sap", amount_column: "DMBTR", currency_column: "WAERS",
    column_map: { posting_date: "BUDAT", document_date: "BLDAT", account: "HKONT",
                  username: "UNAME", description: "SGTXT", source_doc: "BELNR",
                  entry_ref: "BELNR", entry_created_date: "CPUDT" },
    high_risk_users: [], max_universe_size: 200, review_mode: "human",
    report_lang: "en",
  });
  const [autodetecting, setAutodetecting] = useState(false);
  const [detection, setDetection] = useState(null);
  const autoDetect = async () => {
    if (!file) { toast.error("Choose a CSV extract first to auto-detect."); return; }
    setAutodetecting(true);
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
      toast.success(`Auto-detected (${Math.round((d.confidence || 0) * 100)}% confidence)`);
    } catch (e) { toast.error(e.message); }
    setAutodetecting(false);
  };
  const yamlOf = () => {
    const c = config, m = c.column_map;
    const map = Object.entries(m).filter(([, v]) => v).map(([k, v]) => `    ${k}: ${v}`).join("\n");
    const users = c.high_risk_users.length ? `\nrisk_context:\n  high_risk_users: [${c.high_risk_users.join(", ")}]` : "";
    return `run_id: ${c.run_id}\nperiod_end: '${c.period_end}'\nmateriality: {overall: ${c.overall}, performance: ${c.performance}, currency: ${c.currency}}\nsource:\n  system: ${c.system}\n  amount_column: ${c.amount_column}\n  currency_column: ${c.currency_column}\n  column_map:\n${map}${users}\nreview:\n  max_universe_size: ${c.max_universe_size}\n  overflow_policy: stratify\n  pack_size: 20\n  mode: ${c.review_mode}\nllm_privacy: {mode: zero_retention, pii_scrubbing: true}\nreport_lang: {lang: ${c.report_lang || "en"}}\nreviewer: {name: jdoe}\n`;
  };
  const start = async () => {
    if (!file) { toast.error("Choose a CSV extract first."); return; }
    if (!config.run_id.trim()) { toast.error("Enter a run ID."); return; }
    setBusy(true);
    try {
      const r = await api.createEngagement(yamlOf(), file);
      if (r.detail) throw new Error(r.detail);
      toast.success(`Started ${r.started} — pipeline running.`);
      onStarted(r.started);
    } catch (e) { toast.error(e.message); }
    setBusy(false);
  };
  return (
    <Card className="rounded-xl border-hairline">
      <CardHeader className="border-b border-hairline py-3.5">
        <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">New engagement</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 pt-5">
        <div>
          <Label htmlFor="csv" className="text-xs uppercase tracking-wider text-ink-soft">{STRINGS[localStorage.getItem("jeagent_lang") || "en"].csvExtract}</Label>
          <Input id="csv" type="file" accept=".csv" className="mt-1.5 cursor-pointer file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:text-xs"
                 onChange={e => setFile(e.target.files[0])} />
          <p className="mt-1.5 text-[11.5px] text-ink-faint">
            {file ? `Selected: ${file.name}` : STRINGS[localStorage.getItem("jeagent_lang") || "en"].noFile}</p>
        </div>
        <ConfigForm config={config} setConfig={setConfig} onAutodetect={autoDetect}
                    autodetecting={autodetecting} detection={detection} />
        <Button disabled={busy} className="bg-amber text-white hover:bg-amber/85" onClick={start}>
          {busy ? "Starting…" : "▶ Start run"}</Button>
      </CardContent>
    </Card>
  );
}

function SectionTitle({ children }) {
  return <h3 className="mb-3 mt-1 text-[11.5px] font-semibold uppercase tracking-[0.15em] text-ink-faint">{children}</h3>;
}

function ConfigForm({ config, setConfig, onAutodetect, autodetecting, detection }) {
  const set = (k) => (e) => setConfig({ ...config, [k]: e.target.value });
  const setCol = (k) => (e) => setConfig({
    ...config, column_map: { ...config.column_map, [k]: e.target.value } });
  const users = config.high_risk_users.join(", ");
  const inp = "mt-1 h-8 text-[13px]";
  return (
    <div className="space-y-5 rounded-xl border border-hairline p-5">
      <div>
        <div className="flex items-center justify-between">
          <SectionTitle>Engagement</SectionTitle>
          {onAutodetect && (
            <Button size="xs" variant="outline" onClick={onAutodetect} disabled={autodetecting}>
              {autodetecting ? "Detecting…" : "✨ Auto-detect from CSV"}</Button>)}
        </div>
        {detection && (
          <p className="-mt-1 mb-2 text-[11.5px] text-ink-soft">
            Auto-detected mapping (confidence {(detection.confidence * 100).toFixed(0)}%).
            {detection.notes?.length ? ` ${detection.notes.join(" ")}` : ""}</p>)}
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="text-xs text-ink-soft">Run ID</Label>
            <Input className={inp} value={config.run_id} onChange={set("run_id")} /></div>
          <div><Label className="text-xs text-ink-soft">Period end</Label>
            <Input className={inp} type="date" value={config.period_end} onChange={set("period_end")} /></div>
        </div>
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Materiality</SectionTitle>
        <div className="grid grid-cols-3 gap-3">
          <div><Label className="text-xs text-ink-soft">Overall</Label>
            <Input className={inp} type="number" value={config.overall} onChange={set("overall")} /></div>
          <div><Label className="text-xs text-ink-soft">Performance</Label>
            <Input className={inp} type="number" value={config.performance} onChange={set("performance")} /></div>
          <div><Label className="text-xs text-ink-soft">Currency</Label>
            <Input className={inp} value={config.currency} onChange={set("currency")} /></div>
        </div>
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Source system</SectionTitle>
        <div className="grid grid-cols-3 gap-3">
          <div><Label className="text-xs text-ink-soft">System</Label>
            <Select value={config.system} onValueChange={v => setConfig({ ...config, system: v })}>
              <SelectTrigger className={inp}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="sap">SAP</SelectItem>
                <SelectItem value="oracle">Oracle</SelectItem>
                <SelectItem value="generic">Generic</SelectItem>
              </SelectContent>
            </Select></div>
          <div><Label className="text-xs text-ink-soft">Amount column</Label>
            <Input className={inp} value={config.amount_column} onChange={set("amount_column")} /></div>
          <div><Label className="text-xs text-ink-soft">Currency column</Label>
            <Input className={inp} value={config.currency_column} onChange={set("currency_column")} /></div>
        </div>
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Column mapping</SectionTitle>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {[["posting_date","Posting date"],["document_date","Document date"],["account","Account"],
            ["username","Username"],["description","Description"],["source_doc","Source doc"],
            ["entry_ref","Entry ref"],["entry_created_date","Created date"],["entry_type","Entry type"]].map(([k, lbl]) => (
            <div key={k}><Label className="text-xs text-ink-soft">{lbl}</Label>
              <Input className={inp} value={config.column_map[k] || ""} onChange={setCol(k)} /></div>))}
        </div>
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Risk</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="text-xs text-ink-soft">High-risk users (comma separated)</Label>
            <Input className={inp} value={users}
                   onChange={e => setConfig({ ...config, high_risk_users:
                     e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} /></div>
          <div><Label className="text-xs text-ink-soft">Universe size cap</Label>
            <Input className={inp} type="number" value={config.max_universe_size}
                   onChange={e => setConfig({ ...config, max_universe_size: +e.target.value })} /></div>
        </div>
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Review</SectionTitle>
        <div className="flex gap-2">
          {[["human","👤 Human review"],["ai","🤖 AI review"]].map(([m, lbl]) => (
            <Button key={m} variant={config.review_mode === m ? "default" : "outline"} size="sm"
                    className={config.review_mode === m ? "flex-1 bg-ink text-white hover:bg-ink/85" : "flex-1"}
                    onClick={() => setConfig({ ...config, review_mode: m })}>{lbl}</Button>))}
        </div>
        {config.review_mode === "ai" && (
          <p className="mt-2 text-[11.5px] leading-relaxed text-ink-soft">
            The engine auto-decides inspect/accept from triage (reviewer “ai-reviewer”). Only for
            practice/demo or clean populations — AI review is not equivalent to human substantive testing.</p>)}
      </div>

      <Separator className="bg-hairline" />
      <div>
        <SectionTitle>Report language</SectionTitle>
        <div className="flex gap-2">
          {[["en","🇬🇧 English"],["fr","🇫🇷 Français"]].map(([code, lbl]) => (
            <Button key={code} variant={(config.report_lang || "en") === code ? "default" : "outline"} size="sm"
                    className={(config.report_lang || "en") === code ? "flex-1 bg-ink text-white hover:bg-ink/85" : "flex-1"}
                    onClick={() => setConfig({ ...config, report_lang: code })}>{lbl}</Button>))}
        </div>
        <p className="mt-2 text-[11px] text-ink-faint">
          Affects the generated report (cover, sections, tables). UI language is the EN/FR switch at the top.</p>
      </div>
    </div>
  );
}

// ————————————————————————————— CONFIGURE (model connection)
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
    <Card className="mx-auto max-w-xl rounded-xl border-hairline">
      <CardHeader className="border-b border-hairline py-3.5">
        <CardTitle className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-soft">Model connection</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-5">
        <p className="text-[12.5px] text-ink-soft">
          Any OpenAI-compatible endpoint: Gemini, Ollama, vLLM, LM Studio, OpenRouter, Azure.
          Verify credentials before starting a run.</p>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="text-xs text-ink-soft">Base URL</Label>
            <Input className="mt-1 h-8 text-[13px]" value={base} onChange={e => setBase(e.target.value)} /></div>
          <div><Label className="text-xs text-ink-soft">Model ID</Label>
            <Input className="mt-1 h-8 text-[13px]" value={model} onChange={e => setModel(e.target.value)} /></div>
        </div>
        <div><Label className="text-xs text-ink-soft">API key</Label>
          <Input className="mt-1 h-8 font-mono text-[13px]" type="password" placeholder="(session only)"
                 value={key} onChange={e => setKey(e.target.value)} /></div>
        <div className="flex items-center gap-3 pt-1">
          <Button size="sm" disabled={busy} className="bg-amber text-white hover:bg-amber/85" onClick={test}>
            {busy ? "Testing…" : "🔌 Test connection"}</Button>
          {res?.ok && (
            <span className="text-[12.5px] font-semibold text-emerald-700">
              ✔ {res.data.latency_ms} ms · tools {res.data.tool_support ? "OK" : "n/a"}</span>)}
          {res && !res.ok && <span className="text-[12.5px] text-red-700">✖ {res.err}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default App;
