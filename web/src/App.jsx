import { Fragment, useEffect, useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { Toaster, toast } from "sonner";
import {
  LayoutDashboard, FilePlus2, Activity, ClipboardCheck, FileText,
  Settings, Scale, PanelLeftClose, PanelLeftOpen, ChevronRight,
  Search, Download, Eye, Trash2, CircleCheck, Loader2,
} from "lucide-react";
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

/* ════════════════════════════════════════════════════════════════════
   JE Agent console v1.1 — "The Ledger" design
   Warm paper · ink · single amber accent · halftone texture motif
   Sidebar shell · editorial type · GSAP micro-motion
   ════════════════════════════════════════════════════════════════════ */

const ICONS = {
  engage: LayoutDashboard, new: FilePlus2, monitor: Activity,
  review: ClipboardCheck, report: FileText, configure: Settings,
};

/* Halftone dot-grid texture (the signature motif) */
function Halftone({ className = "", flip = false }) {
  return (
    <svg aria-hidden className={`pointer-events-none absolute ${className}`}
      style={flip ? { transform: "scaleX(-1)" } : undefined}>
      <defs>
        <pattern id="dots" width="14" height="14" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.6" fill="currentColor" />
        </pattern>
        <linearGradient id="fade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="white" stopOpacity="0.9" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id="dotmask"><rect width="100%" height="100%" fill="url(#fade)" /></mask>
      </defs>
      <rect width="100%" height="100%" fill="url(#dots)" mask="url(#dotmask)" />
    </svg>
  );
}

/* Organic ink blob (login hero) */
function InkBlob({ className }) {
  return (
    <svg aria-hidden viewBox="0 0 400 300" className={`pointer-events-none absolute ${className}`}>
      <path d="M52,-118 C120,-96 189,-58 213,3 C237,64 216,148 158,190 C100,232 5,232 -63,197
               C-131,162 -172,92 -176,22 C-180,-48 -146,-117 -89,-142 C-32,-167 16,-140 52,-118 Z"
            fill="currentColor" transform="translate(-40 -20)" />
    </svg>
  );
}

function App() {
  const [key, setKey] = useState(sessionStorage.getItem("jeagent_key") || "");
  return key ? (
    <AppInner onSignOut={() => { sessionStorage.removeItem("jeagent_key"); setKey(""); }} />
  ) : (
    <Login onOk={setKey} />
  );
}

/* ————————————————— LOGIN — editorial cover page */
function Login({ onOk }) {
  const [k, setK] = useState("");
  const [err, setErr] = useState(null);
  const root = useRef(null);
  useGSAP(() => {
    gsap.from(".lg-blob", { scale: 0.7, autoAlpha: 0, duration: 1.1, ease: "power3.out" });
    gsap.from(".lg-line", { yPercent: 110, duration: 0.8, stagger: 0.09, ease: "power4.out", delay: 0.15 });
    gsap.from(".lg-form", { y: 24, autoAlpha: 0, duration: 0.6, delay: 0.55, ease: "power2.out" });
  }, { scope: root });

  const submit = async () => {
    try {
      const r = await fetch(`${BASE}/api/runs`, { headers: { "X-API-Key": k } });
      if (!r.ok) throw new Error();
      sessionStorage.setItem("jeagent_key", k); onOk(k);
    } catch { setErr(true); }
  };
  return (
    <div ref={root} className="grid min-h-screen bg-paper lg:grid-cols-[1.1fr_1fr]">
      {/* left: cover — full ink panel, guaranteed contrast */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-ink p-12 lg:flex">
        <InkBlob className="lg-blob -left-40 -top-40 h-[900px] w-[900px] text-[#2a2926]" />
        <Halftone className="bottom-10 right-10 h-44 w-72 text-amber/80" flip />
        <div className="relative z-10 flex items-center gap-2.5">
          <Scale className="h-5 w-5 text-amber" strokeWidth={2.4} />
          <span className="text-sm font-bold tracking-tight text-paper">JE Agent</span>
        </div>
        <div className="relative z-10 max-w-md">
          <h1 className="text-[46px] font-extrabold leading-[1.05] tracking-tight text-paper">
            <span className="block overflow-hidden"><span className="lg-line block">Journal-entry</span></span>
            <span className="block overflow-hidden"><span className="lg-line block">testing,</span></span>
            <span className="block overflow-hidden"><span className="lg-line block text-amber">decided.</span></span>
          </h1>
          <p className="mt-5 max-w-xs text-[13px] leading-relaxed text-paper/60">
            ISA 240 / AS 2401 risk scanning for journal entries — deterministic rules,
            AI-assisted triage, hash-chained auditor judgment.</p>
        </div>
        <div className="relative z-10 text-[11px] font-medium uppercase tracking-[0.2em] text-paper/50">
          Local execution · your data stays here</div>
      </div>

      {/* right: form */}
      <div className="flex items-center justify-center p-8">
        <div className="lg-form w-full max-w-sm">
          <div className="flex items-center gap-2.5 lg:hidden">
            <Scale className="h-5 w-5 text-amber" /><span className="font-bold">JE Agent</span>
          </div>
          <Label htmlFor="key" className="mt-6 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-faint lg:mt-0">
            API key</Label>
          <Input id="key" type="password" value={k} onChange={e => setK(e.target.value)}
                 onKeyDown={e => e.key === "Enter" && submit()}
                 className="mt-1.5 h-10 font-mono" placeholder="••••••••••" autoFocus />
          {err && <p className="mt-2 text-xs text-red-700">That key didn't work — check and retry.</p>}
          <Button className="mt-5 h-10 w-full bg-ink text-white hover:bg-ink/85" onClick={submit}>Continue →</Button>
          <p className="mt-6 text-center text-[11px] leading-relaxed text-ink-faint">
            Deterministic rules · AI-assisted priority · human judgment.<br/>
            Not a fraud detector; substantive testing remains yours.</p>
        </div>
      </div>
    </div>
  );
}

const PAGES = ["engage", "new", "monitor", "review", "report", "configure"];

function AppInner({ onSignOut }) {
  const [runs, setRuns] = useState(null);
  const [runsLoading, setRunsLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState("engage");
  const [lang, setLang] = useState(() => localStorage.getItem("jeagent_lang") || "en");
  const [collapsed, setCollapsed] = useState(false);
  const t = STRINGS[lang];
  const setL = (l) => { localStorage.setItem("jeagent_lang", l); setLang(l); };

  const refresh = () => { setRunsLoading(true);
    return api.runs().then(r => { setRuns(r.runs); setRunsLoading(false); return r.runs; })
    .catch(() => { setRunsLoading(false); sessionStorage.removeItem("jeagent_key"); onSignOut(); }); };
  useEffect(() => { if (!runs) refresh(); }, []);

  const hasRun = !!selected;
  const opened = (id) => { setSelected(id); setPage("monitor"); };

  const mainRef = useRef(null);
  useGSAP(() => {
    gsap.fromTo(mainRef.current, { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.38, ease: "power2.out",
      clearProps: "transform" });
  }, [page]);

  const nav = PAGES.map(id => ({
    id, label: t.pages[id], icon: ICONS[id],
    disabled: !hasRun && ["monitor","review","report"].includes(id),
  }));

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      {/* ———— SIDEBAR ———— */}
      <aside className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-hairline bg-card
                         transition-[width] duration-300 ${collapsed ? "w-[68px]" : "w-[228px]"}`}>
        <div className="flex items-center gap-2.5 px-4 py-5">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-ink">
            <Scale className="size-4.5 text-amber" strokeWidth={2.2} /></div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-bold tracking-tight">JE Agent</div>
              <div className="truncate text-[10px] font-medium uppercase tracking-[0.16em] text-ink-faint">ISA 240 / AS 2401</div>
            </div>)}
        </div>

        <nav className="mt-2 flex-1 space-y-0.5 px-2.5">
          {nav.map(({id, label, icon: Icon, disabled}) => (
            <button key={id} disabled={disabled}
              onClick={() => setPage(id)}
              title={collapsed ? label : undefined}
              className={`group relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-semibold transition-all
                ${page === id ? "bg-ink text-paper shadow-[0_2px_10px_rgba(31,30,28,0.25)]"
                               : disabled ? "cursor-not-allowed text-ink-faint/50"
                               : "text-ink-soft hover:bg-muted hover:text-ink"}`}>
              <Icon className={`size-4 shrink-0 ${page === id ? "text-amber" : ""}`} strokeWidth={2.2} />
              {!collapsed && <span className="truncate">{label}</span>}
              {!collapsed && page === id && <ChevronRight className="ml-auto size-3.5 opacity-60" />}
            </button>))}
        </nav>

        <Separator className="mx-4 bg-hairline" />
        <div className="space-y-0.5 px-2.5 py-3">
          <button onClick={() => setCollapsed(c => !c)}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-semibold text-ink-soft transition-colors hover:bg-muted hover:text-ink">
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            {!collapsed && <span>Collapse</span>}
          </button>
          <button onClick={onSignOut}
            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-semibold text-ink-soft transition-colors hover:bg-muted hover:text-red-700">
            <Settings className="size-4 hidden" />
            <LogOutIcon collapsed={collapsed} t={t} />
          </button>
        </div>
      </aside>

      {/* ———— MAIN ———— */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-hairline bg-paper/85 backdrop-blur-md">
          <div className="flex min-h-[60px] items-center justify-between gap-4 px-6 py-3">
            <div className="min-w-0">
              <h2 className="truncate text-[17px] font-bold tracking-tight">{t.pages[page]}</h2>
              {selected && <div className="font-mono text-[11px] text-ink-faint">{selected}</div>}
            </div>
            <div className="flex shrink-0 items-center gap-2.5">
              <LangToggle lang={lang} setL={setL} />
            </div>
          </div>
        </header>

        <main ref={mainRef} className="flex-1 px-6 pb-14 pt-5">
          {page === "configure" && <Configure />}
          {page === "new" && <NewEngagement onStarted={opened} />}
          {page === "engage" && (
            <Engagements runs={runs || []} runsLoading={runsLoading} selected={selected} t={t}
                         onSelect={(id) => { hasRun ? opened(id) : setSelected(id); }}
                         refresh={refresh} onNew={() => setPage("new")} />)}
          {hasRun && page === "monitor" && <Monitor runId={selected} />}
          {hasRun && page === "review" && <Review runId={selected} />}
          {hasRun && page === "report" && <Report runId={selected} />}
          {!hasRun && ["monitor","review","report"].includes(page) && (
            <Card className="rounded-2xl border-hairline"><CardContent className="py-16 text-center">
              <Halftone className="mx-auto mb-4 h-16 w-32 text-ink/20" />
              <p className="text-sm text-ink-faint">Open an engagement first — pick one from Engagements.</p>
            </CardContent></Card>)}
        </main>
      </div>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}

function LogOutIcon({ collapsed, t }) {
  return (<><LogOut className="size-4" /><span>{collapsed ? "" : t.signOut}</span></>);
}
import { LogOut } from "lucide-react";

function LangToggle({ lang, setL }) {
  return (
    <div className="flex overflow-hidden rounded-lg border border-hairline bg-card">
      {["en","fr"].map(l => (
        <button key={l} onClick={() => setL(l)}
          className={`px-2.5 py-1 text-[11px] font-bold uppercase transition-colors
            ${lang === l ? "bg-ink text-paper" : "bg-transparent text-ink-faint hover:text-ink-soft"}`}>{l}</button>))}
    </div>);
}

function StatusChip({ status }) {
  if (!status) return <span className="text-[11px] uppercase tracking-wide text-ink-faint">no status</span>;
  const fin = status === "finalized";
  return fin ? (
    <Badge variant="outline" className="gap-1.5 border-emerald-800/30 bg-transparent text-emerald-800">
      <CircleCheck className="size-3" />{status.replace(/_/g," ")}</Badge>
  ) : (
    <Badge className="gap-1.5 border-0 bg-amber-soft text-amber hover:bg-amber-soft">
      <Loader2 className="size-3 animate-none" />{status.replace(/_/g," ")}</Badge>);
}

/* ————————————————— ENGAGEMENTS dashboard */
function Engagements({ runs, runsLoading, onSelect, selected, refresh, onNew, t }) {
  const grid = useRef(null);
  useGSAP(() => {
    gsap.from(".kpi-card", { y: 14, autoAlpha: 0, duration: 0.5, stagger: 0.07, ease: "power3.out", clearProps: "all" });
    gsap.from(".halftone-hero", { backgroundPositionX: "-200px", duration: 1.2, ease: "power2.out" });
  }, { scope: grid, dependencies: [runs.length] });

  const finalized = runs.filter(r => r.status === "finalized").length;
  const awaiting = runs.filter(r => r.status === "awaiting_review").length;
  const lines = runs.reduce((s, r) => s + (r.population || 0), 0);

  return (
    <div ref={grid} className="space-y-4">
      {/* hero strip */}
      <div className="halftone-hero relative overflow-hidden rounded-2xl border border-hairline bg-card p-6">
        <Halftone className="right-0 top-0 h-full w-80 text-ink/10" />
        <div className="relative z-10 max-w-xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber">{t.kpi.engagements}</div>
          <h3 className="mt-1 text-2xl font-extrabold tracking-tight">{runs.length} engagements · {lines.toLocaleString()} lines tested</h3>
          <p className="mt-1 text-[12.5px] text-ink-soft">{awaiting} awaiting review · {finalized} finalized</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[{ l: t.kpi.engagements, v: runs.length }, { l: t.kpi.finalized, v: finalized },
          { l: t.kpi.awaiting, v: awaiting }, { l: t.kpi.lines, v: lines.toLocaleString() }].map(({l, v}) => (
          <Card key={l} className="kpi-card rounded-xl border-hairline shadow-[0_1px_2px_rgba(31,30,28,0.05)]">
            <CardContent className="px-4 py-4">
              <div className="font-mono text-[26px] font-bold tabular-nums leading-none">{v}</div>
              <div className="mt-2 text-[10.5px] font-medium uppercase tracking-[0.15em] text-ink-faint">{l}</div>
            </CardContent>
          </Card>))}
      </div>

      <Card className="rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardHeader className="flex-row items-center justify-between border-b border-hairline py-4">
          <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">{t.engagements}</CardTitle>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={refresh}>{t.refresh}</Button>
            <Button size="sm" className="bg-accent text-white hover:bg-accent/85" onClick={onNew}>{t.newBtn}</Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {runsLoading && (
            <div className="space-y-2.5 px-4 py-4">
              {[0,1,2].map(i => <div key={i} className="h-9 animate-pulse rounded-md bg-muted" />)}
            </div>)}
          {!runsLoading && runs.length === 0 && (
            <div className="px-4 py-14 text-center text-sm text-ink-faint">{t.noRuns}</div>)}
          {!runsLoading && runs.map(r => (
            <div key={r.run_id}
              onClick={() => onSelect(r.run_id)}
              className={`group flex cursor-pointer items-center justify-between border-b border-hairline px-5 py-3 last:border-0 transition-colors
                ${selected === r.run_id ? "bg-amber-soft/50" : "hover:bg-paper"}`}>
              <div className="flex min-w-0 items-center gap-3.5">
                <div className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-paper font-mono text-[10px] font-bold text-ink-soft sm:flex">
                  {(r.status || "?")[0].toUpperCase()}</div>
                <div className="min-w-0">
                  <div className="truncate font-mono text-[13.5px] font-semibold">{r.run_id}</div>
                  <div className="mt-0.5 text-[11px] text-ink-faint">
                    {t.phase} {r.phase || "—"} · {(r.population || 0).toLocaleString()} lines</div>
                </div>
              </div>
              <div className="ml-3 flex shrink-0 items-center gap-2.5">
                <StatusChip status={r.status} />
                <button title={t.deleteTitle} onClick={(e) => { e.stopPropagation();
                  if (window.confirm(t.deleteConfirm(r.run_id))) {
                    api.deleteRun(r.run_id).then(() => { refresh(); toast.success(`${r.run_id} deleted`); })
                       .catch(err => toast.error(err.message)); } }}
                  className="rounded-md p-1.5 text-ink-faint opacity-0 transition-all hover:bg-destructive/10 hover:text-red-700 group-hover:opacity-100">
                  <Trash2 className="size-3.5" /></button>
                <ChevronRight className="size-4 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
              </div>
            </div>))}
        </CardContent>
      </Card>
    </div>
  );
}

/* ————————————————— MONITOR */
function Monitor({ runId }) {
  const [m, setM] = useState(null);
  const [d, setD] = useState(null);
  const barsRef = useRef(null);
  useEffect(() => {
    api.metrics(runId).then(setM).catch(() => {});
    api.runDetail(runId).then(setD).catch(() => {});
  }, [runId]);
  useGSAP(() => {
    gsap.from(".rule-bar", { scaleX: 0, transformOrigin: "left center", duration: 0.7, stagger: 0.05,
                             ease: "power3.out", clearProps: "transform" });
  }, { scope: barsRef, dependencies: [!!m] });
  if (!m) return <Card className="rounded-2xl border-hairline"><CardContent className="py-12 text-center text-sm text-ink-faint">Loading metrics…</CardContent></Card>;
  const maxCount = Math.max(1, ...Object.values(m.rule_counts || {}));
  return (
    <div ref={barsRef} className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[["Lines", m.population], ["Flagged docs", m.flagged_docs],
          ["Universe", m.universe_selected], ["Status", m.status]].map(([l, v]) => (
          <Card key={l} className="rounded-xl border-hairline shadow-[0_1px_2px_rgba(31,30,28,0.05)]">
            <CardContent className="px-4 py-4">
              <div className="font-mono text-[26px] font-bold tabular-nums leading-none">{v}</div>
              <div className="mt-2 text-[10.5px] font-medium uppercase tracking-[0.15em] text-ink-faint">{l}</div>
            </CardContent>
          </Card>))}
      </div>

      <Card className="rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardHeader className="border-b border-hairline py-4">
          <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Rule outcomes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2.5 pt-5">
          {Object.entries(m.rule_counts).map(([k, v]) => (
            <div key={k} className="flex items-center gap-3">
              <span className="w-44 shrink-0 truncate font-mono text-[12px] text-ink-soft">{k}</span>
              <div className="h-6 flex-1 overflow-hidden rounded-md bg-muted/70">
                <div className="rule-bar flex h-full items-center justify-end rounded-md bg-ink pr-2"
                     style={{ width: `${Math.max(2, v / maxCount * 100)}%` }}>
                  {v / maxCount > 0.18 && (
                    <span className="font-mono text-[10.5px] font-bold tabular-nums text-paper">{v.toLocaleString()}</span>)}
                </div>
              </div>
              {(v / maxCount <= 0.18) && (
                <span className="w-14 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink-faint">{v.toLocaleString()}</span>)}
            </div>))}
        </CardContent>
      </Card>

      <Card className="rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardHeader className="border-b border-hairline py-4">
          <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Audit events</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {(d?.events || []).map((e, i) => (
            <div key={i} className="flex items-baseline gap-3 border-b border-hairline px-5 py-2.5 text-[12.5px] last:border-0">
              <span className="font-mono text-[11px] text-ink-faint">{new Date(e.ts).toLocaleTimeString()}</span>
              <b>{e.kind}</b><span className="text-ink-soft">{e.detail}</span>
            </div>))}
          {!d?.events?.length && (
            <div className="px-4 py-10 text-center text-sm text-ink-faint">No events recorded yet.</div>)}
        </CardContent>
      </Card>
    </div>
  );
}

/* ————————————————— REVIEW — the ledger */
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
  if (!u) return <Card className="rounded-2xl border-hairline"><CardContent className="py-12 text-center text-sm text-ink-faint">Loading review queue…</CardContent></Card>;
  const decided = u.entries.filter(e => e.decision !== "pending").length;
  const pending = u.entries.length - decided;
  const pctDone = Math.round(decided / (u.entries.length || 1) * 100);

  const ask = (ref, decision) => setReasoning({ ref, decision, text: "" });
  const confirm = async () => {
    const { ref, decision, text } = reasoning;
    if (!text.trim()) { toast.error("A reason is required."); return; }
    await api.saveDecisions(runId, reviewer, [{ entry_ref: ref, decision, reason: text }]);
    setReasoning({ ref: null, decision: null, text: "" });
    toast.success(`Recorded ${decision} for ${ref}`, { description: "hash-chained" });
    load();
  };
  const finalize = async () => {
    toast.loading("Finalizing — triage/narrative if missing…", { id: "fin" });
    try {
      const r = await api.finalize(runId);
      if (r.status === "finalized") {
        toast.success(`Finalized — ${r.artifacts.join(", ")}`, { id: "fin", duration: 6000 });
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
    <div className="space-y-4">
      {/* progress header */}
      <Card className="relative overflow-hidden rounded-2xl border-hairline bg-card">
        <Halftone className="right-0 top-0 h-full w-64 text-ink/10" />
        <CardContent className="relative z-10 flex flex-wrap items-center gap-x-8 gap-y-4 py-5">
          <div className="min-w-40 flex-1">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-faint">Progress</div>
            <div className="mt-1 text-2xl font-extrabold tabular-nums tracking-tight">{pctDone}%</div>
            <div className="mt-2 h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-amber transition-all duration-500" style={{ width: `${pctDone}%` }} />
            </div>
            <p className="mt-1.5 text-[11.5px] text-ink-soft">{decided} decided · {pending} pending of {u.selected}</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Input value={reviewer} onChange={e => setReviewer(e.target.value)}
                   className="h-9 w-32 bg-card font-mono text-xs" />
            <Button size="default" className="h-9 bg-ink text-white hover:bg-ink/85" onClick={finalize}>
              🏁 Finalize</Button>
          </div>
        </CardContent>
      </Card>

      {/* reason slip */}
      {reasoning.ref && (
        <Card className="rounded-xl border-amber/50 shadow-[0_8px_28px_rgba(180,83,9,0.10)]">
          <CardContent className="pt-4">
            <Label className="text-xs uppercase tracking-wider text-ink-soft">
              Reason for {reasoning.decision} on <span className="font-mono">{reasoning.ref}</span></Label>
            <textarea autoFocus value={reasoning.text}
              onChange={e => setReasoning({ ...reasoning, text: e.target.value })}
              onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) confirm(); }}
              className="mt-1.5 min-h-[84px] w-full rounded-lg border border-hairline bg-card p-3 font-mono text-[12.5px] outline-none transition-colors focus:border-amber/60" />
            <div className="mt-2.5 flex items-center gap-2">
              <Button size="sm" className="bg-amber text-white hover:bg-amber/85" onClick={confirm}>✔ Confirm</Button>
              <Button size="sm" variant="ghost" onClick={() => setReasoning({ ref: null, decision: null, text: "" })}>Cancel</Button>
              <span className="ml-auto text-[11px] text-ink-faint">Ctrl/Cmd+Enter</span>
            </div>
          </CardContent>
        </Card>)}

      {/* THE LEDGER */}
      <Card className="overflow-hidden rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">entry</TableHead>
                <TableHead>rules</TableHead>
                <TableHead className="text-right">amount</TableHead>
                <TableHead>decision</TableHead>
                <TableHead className="pr-5" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {u.entries.slice(0, 60).map((e) => (
                <Fragment key={e.entry_ref}>
                  <TableRow className={`group ${detail?.entry_ref === e.entry_ref ? "bg-amber-soft/30" : ""}`}>
                    <TableCell className="pl-5">
                      <button onClick={() => toggle(e.entry_ref)}
                        className="font-mono text-[13px] font-bold underline-offset-2 hover:text-amber hover:underline">{e.entry_ref}</button>
                    </TableCell>
                    <TableCell className="font-mono text-[12px] text-ink-soft">{e.rules_hit}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {e.abs_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</TableCell>
                    <TableCell><DecisionBadge decision={e.decision} /></TableCell>
                    <TableCell className="whitespace-nowrap pr-5 text-right">
                      {e.decision === "pending" ? (
                        <span className="inline-flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                          <Button size="xs" className="bg-amber text-white hover:bg-amber/85"
                                  onClick={() => ask(e.entry_ref, "inspect")}>inspect</Button>
                          <Button size="xs" variant="outline" onClick={() => ask(e.entry_ref, "accept")}>accept</Button>
                        </span>
                      ) : <CircleCheck className="size-4 text-emerald-700" />}
                    </TableCell>
                  </TableRow>

                  {detail && detail.entry_ref === e.entry_ref && (
                    <TableRow key={`${e.entry_ref}-d`} className="hover:bg-transparent">
                      <TableCell colSpan={5} className="border-l-[3px] border-amber bg-paper px-7 pb-5">
                        {detail.lines ? (
                          <div className="pt-2 text-[12px]">
                            <div className={`mb-2.5 text-[11px] font-semibold ${Object.keys(detail.flags || {}).length ? "text-amber" : "text-ink-faint"}`}>
                              {Object.keys(detail.flags || {}).length
                                ? `Rules hit · ${Object.keys(detail.flags).join("  ·  ")}`
                                : "No rule flags reported"}
                            </div>
                            <table className="w-full text-[11.5px]">
                              <thead>
                                <tr className="text-[10px] uppercase tracking-[0.12em] text-ink-faint">
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
                        ) : (
                          <div className="flex items-center gap-2 py-3 text-[11.5px] text-ink-faint">
                            <Loader2 className="size-3.5 animate-spin" /> Loading lines…
                          </div>)}
                      </TableCell>
                    </TableRow>)}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          {u.entries.length > 60 && (
            <p className="border-t border-hairline px-5 py-3 text-[11.5px] text-ink-faint">
              Showing first 60 of {u.entries.length}.</p>)}
        </CardContent>
      </Card>
    </div>
  );
}

function DecisionBadge({ decision }) {
  if (decision === "inspect")
    return <Badge className="border-0 bg-amber-soft text-amber hover:bg-amber-soft">inspect</Badge>;
  if (decision === "accept")
    return <Badge variant="outline" className="bg-transparent text-emerald-800">accept</Badge>;
  return <span className="text-[11px] uppercase tracking-wide text-ink-faint">pending</span>;
}

/* ————————————————— REPORT */
function Report({ runId }) {
  const [m, setM] = useState(null);
  useEffect(() => { api.metrics(runId).then(setM).catch(() => {}); }, [runId]);
  const arts = ["report.pdf", "report.html", "workpaper.xlsx", "flagged_entries.xlsx"];
  const insp = m?.decisions?.inspect || 0, acc = m?.decisions?.accept || 0;
  return (
    <>
      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <Card className="rounded-2xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
          <CardHeader className="border-b border-hairline py-4">
            <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Engagement summary</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 pt-4 md:grid-cols-5">
            {[["Lines", m?.population], ["Flagged", m?.flagged_docs], ["Universe", m?.universe_selected],
              ["Inspect", insp], ["Benford MAD", m?.benford?.mad?.toFixed(4)]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-paper px-4 py-3.5">
                <div className="font-mono text-xl font-bold tabular-nums leading-none">{v ?? "—"}</div>
                <div className="mt-2 text-[10px] font-medium uppercase tracking-[0.15em] text-ink-faint">{l}</div>
              </div>))}
          </CardContent>
        </Card>

        {/* decisions donut */}
        <Card className="rounded-2xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
          <CardHeader className="border-b border-hairline py-4">
            <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Decisions</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-5 pt-4">
            <Donut inspect={insp} accept={acc} />
            <div className="space-y-2 text-[12px]">
              <div className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-amber" />inspect <b className="tabular-nums">{insp}</b></div>
              <div className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-emerald-700" />accept <b className="tabular-nums">{acc}</b></div>
              <div className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-muted" />pending <b className="tabular-nums">{Math.max(0, (m?.universe_selected||0) - insp - acc)}</b></div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardHeader className="border-b border-hairline py-4">
          <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Deliverables</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {arts.map(n => (
            <div key={n} className="group flex items-center justify-between border-b border-hairline px-5 py-3 last:border-0">
              <span className="flex items-center gap-3 font-mono text-[13px]">
                <FileText className="size-4 text-ink-faint" />{n}</span>
              <span className="flex gap-2 opacity-80 transition-opacity group-hover:opacity-100">
                {(n === "report.pdf" || n === "report.html") && (
                  <Button size="xs" variant="secondary" onClick={async () => {
                    try { window.open(await api.artifactUrl(runId, n), "_blank"); }
                    catch (e) { toast.error(e.message); }}}>
                    <Eye className="size-3" />view</Button>)}
                <Button size="xs" variant="outline" onClick={async () => {
                  try { await api.download(runId, n); toast.success(`${n} downloaded`); }
                  catch (e) { toast.error(e.message); }}}>
                  <Download className="size-3" />download</Button>
              </span>
            </div>))}
        </CardContent>
      </Card>

      {m?.benford?.mad != null && (
        <Card className="rounded-xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
          <CardHeader className="border-b border-hairline py-4">
            <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Benford first-digit distribution</CardTitle>
          </CardHeader>
          <CardContent className="pt-5">
            <p className="mb-3 text-[12px] text-ink-soft">
              MAD {m.benford.mad.toFixed(4)} — {m.benford.nigrini_assessment || "—"} (informational, amendment C2).</p>
            <BenfordChart counts={m.benford.counts} />
          </CardContent>
        </Card>)}
    </>
  );
}

function Donut({ inspect, accept }) {
  const R = 34, C = 2 * Math.PI * R;
  const total = Math.max(1, inspect + accept);
  const seg = [
    { frac: inspect / total, color: "#b45309", off: 0 },
    { frac: accept / total, color: "#047857", off: inspect / total },
  ];
  return (
    <svg viewBox="0 0 90 90" className="size-24 -rotate-90">
      <circle cx="45" cy="45" r={R} fill="none" strokeWidth="11" className="stroke-muted" />
      {seg.map((s, i) => s.frac > 0 && (
        <circle key={i} cx="45" cy="45" r={R} fill="none" strokeWidth="11"
          stroke={s.color} strokeDasharray={`${s.frac * C} ${C}`}
          strokeDashoffset={-s.off * C} strokeLinecap="butt" />
      ))}
      <text x="45" y="50" textAnchor="middle" transform="rotate(90 45 45)"
        className="fill-ink font-mono text-[15px] font-bold">{total}</text>
    </svg>);
}

function BenfordChart({ counts }) {
  const digits = ["1","2","3","4","5","6","7","8","9"];
  const observed = digits.map(d => (counts || {})[Number(d)] || 0);
  const total = observed.reduce((a, b) => a + b, 0) || 1;
  const benfordExpected = digits.map(d => Math.log10(1 + 1 / Number(d)));
  const max = Math.max(...observed.map(o => o / total), ...benfordExpected) || 1;
  const wrap = useRef(null);
  useGSAP(() => {
    gsap.from(".ben-bar", { scaleY: 0, transformOrigin: "bottom", duration: 0.65, stagger: 0.05,
                            ease: "power3.out", clearProps: "transform" });
  }, { scope: wrap });
  return (
    <div ref={wrap}>
      <div className="flex h-44 items-end gap-2.5">
        {digits.map((d, i) => {
          const o = observed[i] / total, ex = benfordExpected[i];
          return (
            <div key={d} className="flex flex-1 flex-col items-center gap-1">
              <div className="text-[10px] tabular-nums text-ink-soft">{(o * 100).toFixed(1)}%</div>
              <div className="relative flex h-28 w-full items-end justify-center">
                <div className="absolute bottom-0 w-full border-t border-dashed border-ink/35"
                     style={{ height: `${(ex / max) * 100}%` }} title="Benford expected" />
                <div className="ben-bar relative z-10 w-3/5 rounded-t-sm bg-ink" style={{ height: `${(o / max) * 100}%` }} />
              </div>
              <div className="text-[11px] font-bold">{d}</div>
            </div>);
        })}
      </div>
      <p className="mt-2 text-[11px] text-ink-faint">Solid = observed · dashed line = Benford expected</p>
    </div>
  );
}

/* ————————————————— NEW ENGAGEMENT */
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
        column_map: Object.fromEntries(Object.keys(c.column_map).concat(["entry_type"])
          .map(k => [k, (d.column_map || {})[k] || c.column_map[k] || ""])),
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
      toast.success(`Started ${r.started}`, { description: "pipeline running" });
      onStarted(r.started);
    } catch (e) { toast.error(e.message); }
    setBusy(false);
  };
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {/* upload hero */}
      <label className="group relative block cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed border-hairline bg-card p-8 text-center transition-colors hover:border-amber/60">
        <Halftone className="left-0 top-0 h-full w-48 text-ink/[0.07]" />
        <input type="file" accept=".csv" className="sr-only"
               onChange={e => setFile(e.target.files[0])} />
        <div className="relative z-10">
          <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-ink">
            <FilePlus2 className="size-5 text-amber" /></div>
          <p className="mt-3 text-[15px] font-bold">{file ? file.name : "Drop your journal-entry CSV here"}</p>
          <p className="mt-1 text-[12px] text-ink-faint">
            {file ? "Ready — configure below and start." : "or click to browse · columns auto-detected"}</p>
        </div>
      </label>

      <Card className="rounded-2xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
        <CardHeader className="border-b border-hairline py-4">
          <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5 pt-5">
          <ConfigForm config={config} setConfig={setConfig} onAutodetect={autoDetect}
                      autodetecting={autodetecting} detection={detection} hasFile={!!file} />
          <div className="flex items-center gap-3">
            <Button disabled={busy} className="h-10 bg-amber px-6 text-white hover:bg-amber/85" onClick={start}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : "▶ Start run"}</Button>
            <span className="text-[11.5px] text-ink-faint">Stages verified as it runs</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SectionTitle({ children }) {
  return <h3 className="mb-3 mt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-faint">{children}</h3>;
}

function ConfigForm({ config, setConfig, onAutodetect, autodetecting, detection, hasFile }) {
  const set = (k) => (e) => setConfig({ ...config, [k]: e.target.value });
  const setCol = (k) => (e) => setConfig({
    ...config, column_map: { ...config.column_map, [k]: e.target.value } });
  const users = config.high_risk_users.join(", ");
  const inp = "mt-1 h-9 bg-card text-[13px]";
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center justify-between">
          <SectionTitle>Engagement</SectionTitle>
          {onAutodetect && (
            <Button size="xs" variant="outline" onClick={onAutodetect} disabled={autodetecting || !hasFile}>
              {autodetecting ? <Loader2 className="size-3 animate-spin" /> : "✨ Auto-detect from CSV"}</Button>)}
        </div>
        {detection && (
          <p className="-mt-1 mb-2 rounded-lg bg-emerald-950/5 px-3 py-2 text-[11.5px] text-emerald-900">
            Detected ({(detection.confidence * 100).toFixed(0)}% confidence)
            {detection.notes?.length ? ` — ${detection.notes.join(" ")}` : ""}</p>)}
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
      <div className="grid grid-cols-2 gap-5">
        <div>
          <SectionTitle>Review</SectionTitle>
          <div className="flex gap-2">
            {[["human","👤 Human"],["ai","🤖 AI"]].map(([m, lbl]) => (
              <Button key={m} variant={config.review_mode === m ? "default" : "outline"} size="sm"
                      className={config.review_mode === m ? "flex-1 bg-ink text-white hover:bg-ink/85" : "flex-1"}
                      onClick={() => setConfig({ ...config, review_mode: m })}>{lbl}</Button>))}
          </div>
          {config.review_mode === "ai" && (
            <p className="mt-2 text-[11px] leading-relaxed text-ink-soft">
              Auto-decides from triage (“ai-reviewer”). For practice/demo — not equivalent to human substantive testing.</p>)}
        </div>
        <div>
          <SectionTitle>Report language</SectionTitle>
          <div className="flex gap-2">
            {[["en","🇬🇧 English"],["fr","🇫🇷 Français"]].map(([code, lbl]) => (
              <Button key={code} variant={(config.report_lang || "en") === code ? "default" : "outline"} size="sm"
                      className={(config.report_lang || "en") === code ? "flex-1 bg-ink text-white hover:bg-ink/85" : "flex-1"}
                      onClick={() => setConfig({ ...config, report_lang: code })}>{lbl}</Button>))}
          </div>
          <p className="mt-2 text-[11px] text-ink-faint">Cover, sections & tables of the generated report.</p>
        </div>
      </div>
    </div>
  );
}

/* ————————————————— CONFIGURE */
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
    <Card className="mx-auto max-w-xl rounded-2xl border-hairline shadow-[0_1px_3px_rgba(31,30,28,0.06)]">
      <CardHeader className="border-b border-hairline py-4">
        <CardTitle className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink-soft">Model connection</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3.5 pt-5">
        <p className="text-[12.5px] leading-relaxed text-ink-soft">
          Any OpenAI-compatible endpoint: Gemini, Ollama, vLLM, LM Studio, OpenRouter, Azure.
          Verify credentials before starting a run.</p>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="text-xs text-ink-soft">Base URL</Label>
            <Input className="mt-1 h-9 text-[13px]" value={base} onChange={e => setBase(e.target.value)} /></div>
          <div><Label className="text-xs text-ink-soft">Model ID</Label>
            <Input className="mt-1 h-9 text-[13px]" value={model} onChange={e => setModel(e.target.value)} /></div>
        </div>
        <div><Label className="text-xs text-ink-soft">API key</Label>
          <Input className="mt-1 h-9 font-mono text-[13px]" type="password" placeholder="(session only)"
                 value={key} onChange={e => setKey(e.target.value)} /></div>
        <div className="flex items-center gap-3 pt-1">
          <Button size="sm" disabled={busy} className="h-9 bg-ink text-white hover:bg-ink/85" onClick={test}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : "🔌 Test connection"}</Button>
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

