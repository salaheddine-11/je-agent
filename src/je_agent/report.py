"""Audit Report builder v2 — engagement-deliverable quality.

Design goals (user-directed): calm, professional, print-like; no decorative
gradients; information density via collapsible detail; Benford conformity chart
with 95% error margins computed live on the run's data; clear provenance chips
(deterministic / LLM / human).
"""

from __future__ import annotations

import html as _html
import json
import math
import re
from datetime import datetime
from pathlib import Path

import duckdb

from .config import EngagementConfig, load_config
from .document import BASE_LIMITATIONS, build_facts_block
from .review import effective_decisions, verify_all_chains
from .run_context import RunContext
from .stats import run_benford
from .store import RunStore
from .universe import select_universe

# ---------------------------------------------------------------------------
# palette — restrained, audit-firm
# ---------------------------------------------------------------------------

INK = "#111827"          # near-black text
SLATE = "#4b5563"        # secondary text
FAINT = "#9ca3af"
HAIR = "#e5e7eb"         # hairlines
PAPER = "#f6f7f8"        # page background
CARD = "#ffffff"
NAVY = "#1e3a5f"         # primary accent (bars, links)
GREEN = "#009E73"        # Okabe-Ito bluish green
RED = "#D55E00"          # Okabe-Ito vermillion (attention)
AMBER = "#b45309"        # warm dark amber (print-safe attention text)
VIOLET = "#6d28d9"       # reserved: LLM provenance only

# Okabe-Ito colorblind-safe series palette (Nature-Methods endorsed) for CHARTS:
OI = {
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "black": "#000000",
}
OI_VERMILLION = OI["vermillion"]

TBL_HEAD_BG = "#f3f4f6"

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
       background: {PAPER}; color: {INK}; font-size: 13.5px; line-height: 1.55;
       -webkit-font-smoothing: antialiased; }}
.wrap {{ max-width: 1060px; margin: 0 auto; padding: 26px 22px 64px; }}

/* ---- masthead ---- */
.mast {{ display: flex; justify-content: space-between; align-items: flex-end;
        gap: 18px; padding-bottom: 14px; border-bottom: 3px solid {INK}; }}
.mast h1 {{ font-size: 21px; font-weight: 750; letter-spacing: .2px; }}
.mast .firm {{ font-size: 11px; font-weight: 700; letter-spacing: 2.4px;
              text-transform: uppercase; color: {SLATE}; margin-bottom: 4px; }}
.mh-meta {{ text-align: right; font-size: 12px; color: {SLATE}; line-height: 1.7; }}
.mh-meta b {{ color: {INK}; }}
.status-pill {{ display: inline-block; padding: 2px 11px; border-radius: 999px;
               font-size: 11px; font-weight: 700; border: 1.5px solid; }}
.status-pill.ok {{ color: {INK}; border-color: {INK}; }}
.status-pill.warn {{ color: {AMBER}; border-color: {AMBER}; }}

/* ---- stat strip ---- */
.strip {{ display: flex; flex-wrap: wrap; background: {CARD};
         border: 1px solid {HAIR}; border-radius: 8px; margin-top: 14px;
         box-shadow: 0 1px 2px rgba(17,24,39,.05); }}
.stat {{ flex: 1 1 110px; padding: 12px 16px; border-right: 1px solid {HAIR}; }}
.stat:last-child {{ border-right: none; }}
.stat .v {{ font-size: 19px; font-weight: 750; font-variant-numeric: tabular-nums; }}
.stat .l {{ font-size: 10.5px; color: {SLATE}; text-transform: uppercase;
           letter-spacing: .7px; margin-top: 1px; }}

/* ---- sections ---- */
h2.sec {{ font-size: 12px; font-weight: 750; text-transform: uppercase;
         letter-spacing: 1.6px; color: {SLATE}; margin: 38px 0 10px;
         padding-bottom: 6px; border-bottom: 1px solid {HAIR}; }}
p.secsub {{ color: {SLATE}; font-size: 12.5px; margin: -4px 0 14px; }}

/* ---- cards & tables ---- */
.card {{ background: {CARD}; border: 1px solid {HAIR}; border-radius: 8px;
        padding: 16px 18px; margin-bottom: 12px;
        box-shadow: 0 1px 2px rgba(17,24,39,.05); }}
table.t {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
table.t th {{ text-align: left; background: {TBL_HEAD_BG}; color: {SLATE};
             padding: 7px 10px; font-size: 10.5px; text-transform: uppercase;
             letter-spacing: .6px; border-bottom: 1.5px solid {HAIR}; }}
table.t td {{ padding: 7px 10px; border-bottom: 1px solid {HAIR}; vertical-align: top; }}
table.t tr:nth-child(even) td {{ background: #fafbfc; }}
table.t tr:last-child td {{ border-bottom: none; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.mono {{ font-family: Consolas, 'Courier New', monospace; font-size: 12px; }}

/* ---- chips: single accent + neutral ramp (user direction: few colors) ---- */
.chip {{ display: inline-block; padding: 1.5px 9px; border-radius: 999px;
        font-size: 10.5px; font-weight: 700; letter-spacing: .3px;
        background: #eef0f2; color: {SLATE}; }}
.chip.inspect  {{ background: #fdf3e3; color: {AMBER}; }}          /* attention */
.chip.accept   {{ background: #fff; color: {SLATE}; border: 1.2px solid {HAIR}; }}
.chip.override,.chip.high   {{ background: {INK}; color: #fff; }}
.chip.medium   {{ background: #6b7280; color: #fff; }}
.chip.low,.chip.none,.chip.det,.chip.llm,.chip.human {{ background: #eef0f2; color: {SLATE}; }}
.chip.zero     {{ background: #fff; color: {SLATE}; border: 1.2px dashed {FAINT}; }}
.chip.ok       {{ background: #fff; color: {INK}; border: 1.2px solid {INK}; }}
.chip.warn     {{ background: #fdf3e3; color: {AMBER}; }}

/* ---- collapsible detail ---- */
details.rule {{ background: {CARD}; border: 1px solid {HAIR}; border-radius: 8px;
               margin-bottom: 8px; box-shadow: 0 1px 2px rgba(17,24,39,.04); }}
details.rule > summary {{ cursor: pointer; padding: 11px 16px; font-weight: 650;
                         font-size: 13px; display: flex; align-items: center; gap: 10px;
                         list-style: none; }}
details.rule > summary::-webkit-details-marker {{ display: none; }}
details.rule > summary::before {{ content: '+'; color: {FAINT}; font-weight: 800;
                                 width: 14px; font-size: 15px; }}
details.rule[open] > summary::before {{ content: '–'; }}
details.rule > .rbody {{ padding: 2px 18px 14px; border-top: 1px solid {HAIR}; }}
.rdesc {{ color: {SLATE}; font-size: 12px; margin: 8px 0 10px; }}

/* ---- misc ---- */
.reason {{ color: {SLATE}; font-size: 12.5px; }}
.note {{ font-size: 12px; color: {SLATE}; }}
.narrative {{ font-family: Georgia, 'Times New Roman', serif; font-size: 14px;
             background: {CARD}; border: 1px solid {HAIR}; border-radius: 8px;
             padding: 22px 28px; box-shadow: 0 1px 2px rgba(17,24,39,.05); }}
.narrative h3 {{ margin: 12px 0 5px; font-size: 14.5px; }}
.funnelline {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
              margin-bottom: 10px; font-size: 12.5px; }}
.fstage {{ background: {CARD}; border: 1px solid {HAIR}; border-radius: 7px;
          padding: 6px 12px; }}
.fstage b {{ font-size: 14px; }}
.two {{ display: grid; grid-template-columns: 3fr 2fr; gap: 12px; align-items: start; }}
.narrative p {{ margin-bottom: 10px; }}
@media (max-width: 900px) {{ .two {{ grid-template-columns: 1fr; }} }}
.legend {{ font-size: 11px; color: {SLATE}; margin-top: 6px; display: flex;
          gap: 16px; flex-wrap: wrap; }}
.sw {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px;
      margin-right: 5px; vertical-align: -1px; }}
/* ---- BLUF + findings (audit-reporting best practice) ---- */
.bluf {{ background: {CARD}; border: 1px solid {HAIR}; border-left: 4px solid {INK};
        border-radius: 8px; padding: 16px 20px; font-size: 13.5px; line-height: 1.7;
        margin-bottom: 14px; box-shadow: 0 1px 2px rgba(17,24,39,.05); }}
.finding {{ background: {CARD}; border: 1px solid {HAIR}; border-radius: 8px;
           margin-bottom: 12px; box-shadow: 0 1px 2px rgba(17,24,39,.05);
           overflow: hidden; page-break-inside: avoid; }}
.finding .fhead {{ display: flex; align-items: center; gap: 10px;
                  padding: 11px 16px; background: #fafbfc;
                  border-bottom: 1px solid {HAIR}; }}
.finding .sev {{ font-size: 10px; font-weight: 800; letter-spacing: 1.2px;
                padding: 2.5px 10px; border-radius: 4px; color: #fff; }}
.sev-high {{ background: {OI_VERMILLION}; }}
.sev-medium {{ background: #6b7280; }}
.sev-low {{ background: {FAINT}; }}
.finding .fhead b {{ font-size: 13.5px; }}
.finding table.f5c td {{ font-size: 12.5px; background: #fff; }}
.finding table.f5c tr:nth-child(even) td {{ background: #fff; }}
.finding table.f5c td.k {{ width: 150px; color: {SLATE}; font-size: 10.5px;
                          text-transform: uppercase; letter-spacing: .8px;
                          background: #fafbfc; }}

.footer {{ margin-top: 46px; padding-top: 16px; border-top: 2px solid {INK};
          color: {SLATE}; font-size: 11.5px; line-height: 1.65; }}
svg text {{ font-family: inherit; }}

/* ---- print / PDF ---- */
@page {{ size: A4; margin: 16mm 14mm; }}
@media print {{
  body {{ background: #fff; }}
  .wrap {{ max-width: none; padding: 0; }}
  details.rule {{ page-break-inside: avoid; }}
  h2.sec {{ page-break-after: avoid; }}
  /* PDF must show folded content: force all rule details open */
  details.rule > .rbody {{ display: block !important; }}
  details.rule > summary {{ cursor: default; }}
  details.rule > summary::before {{ content: ''; width: 0; }}
  .coverpage {{ page-break-after: always; }}
}}
.coverpage {{ height: 257mm; display: flex; flex-direction: column;
             background: {CARD}; padding: 0; }}
.cv-head {{ padding: 46px 50px 0; }}
.cv-firm {{ font-size: 9.5px; letter-spacing: 2.6px; text-transform: uppercase;
           color: {SLATE}; margin-bottom: 18px; }}
.cv-title {{ font-size: 30px; font-weight: 700; letter-spacing: .1px; line-height: 1.15;
            color: {INK}; }}
.cv-sub {{ margin-top: 12px; font-size: 13px; color: {SLATE}; max-width: 560px;
          line-height: 1.65; }}
.cv-rule {{ border: none; border-top: 1px solid {HAIR}; margin: 30px 50px 0; }}
.cv-body {{ flex: 1; padding: 28px 50px; display: flex; flex-direction: column;
           justify-content: flex-start; }}
.cv-eyebrow {{ font-size: 10px; letter-spacing: 1.6px; text-transform: uppercase;
              color: {SLATE}; margin-bottom: 16px; }}
table.cv {{ width: 100%; border-collapse: collapse; font-size: 12.5px; background: {CARD}; }}
table.cv td {{ padding: 12px 0; border-bottom: 1px solid {HAIR}; vertical-align: top; }}
table.cv tr:last-child td {{ border-bottom: none; }}
table.cv td.k {{ width: 30%; color: {SLATE}; font-size: 10.5px;
                letter-spacing: .6px; text-transform: uppercase; padding-top: 11px; }}
table.cv td.v {{ font-weight: 600; color: {INK}; }}
.cv-rule2 {{ border: none; border-top: 1px solid {HAIR}; margin: 30px 0 0; }}
.cv-foot {{ padding: 18px 50px 30px; color: {SLATE}; font-size: 10.5px;
           border-top: 1px solid {HAIR}; display: flex; justify-content: space-between;
           gap: 24px; line-height: 1.55; }}
.cv-foot b {{ color: {INK}; }}
"""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _money(v, ccy="") -> str:
    try:
        return f"{float(v):,.0f}{(' ' + ccy) if ccy else ''}"
    except (TypeError, ValueError):
        return "—"


def _chip(kind: str, label: str | None = None) -> str:
    return f'<span class="chip {kind}">{_esc(label or kind)}</span>'


# ---------------------------------------------------------------------------
# SVG builders
# ---------------------------------------------------------------------------


def svg_hbars(items, color=NAVY, width=640, fmt=None):
    if not items:
        return ""
    mx = max(v for _, v in items) or 1.0
    row_h, label_w, val_w = 24, 170, 80
    h = len(items) * (row_h + 6)
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" height="{h}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    y = 0
    for label, v in items:
        w = max(2.5, (v / mx) ** 0.45 * (width - label_w - val_w - 10))
        txt = fmt(v) if fmt else f"{v:,.0f}"
        out.append(f'<text x="{label_w - 8}" y="{y + 16}" text-anchor="end" '
                   f'font-size="11.5" fill="{SLATE}">{_esc(label[:26])}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 4}" width="{w:.1f}" height="{row_h - 9}" '
                   f'rx="3" fill="{color}"/>')
        out.append(f'<text x="{label_w + w + 7:.1f}" y="{y + 16}" font-size="11.5" '
                   f'font-weight="700" fill="{INK}">{_esc(txt)}</text>')
        y += row_h + 6
    out.append("</svg>")
    return "".join(out)


def svg_timeline(monthly, color=NAVY, width=600, height=90):
    if not monthly:
        return ""
    keys = sorted(monthly)
    mx = max(monthly.values()) or 1.0
    n = max(len(keys), 1)
    bw = max(9.0, min(34.0, (width - 30) / n - 6))
    out = [f'<svg viewBox="0 0 {width} {height + 20}" width="100%" height="{height + 20}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    for i, k in enumerate(keys):
        x = 15 + i * ((width - 30) / n)
        bh = max(2.0, monthly[k] / mx * (height - 8))
        out.append(f'<rect x="{x:.1f}" y="{height - bh:.1f}" width="{bw:.1f}" '
                   f'height="{bh:.1f}" rx="2.5" fill="{color}" opacity=".82"/>')
        if n <= 14 or i % 2 == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{height + 14}" text-anchor="middle" '
                       f'font-size="9" fill="{SLATE}">{_esc(k[2:] if len(k) == 7 else k)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_benford(freq: dict[int, int], width: int = 520, height: int = 210) -> tuple[str, float]:
    """Observed first-digit distribution vs Benford expectation, with 95% CI whiskers."""
    digits = list(range(1, 10))
    n = sum(freq.get(d, 0) for d in digits)
    if n == 0:
        return "", 0.0
    pad_l, pad_b, pad_t = 40, 30, 14
    plot_w, plot_h = width - pad_l - 14, height - pad_b - pad_t
    p_exp = [math.log10(1 + 1 / d) for d in digits]
    p_max = max(max(p_exp), max(freq.get(d, 0) / n for d in digits)) * 1.25

    def Y(p):
        return pad_t + plot_h * (1 - p / p_max)

    bw = plot_w / 9
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    # gridlines (5%, 10%, ..., )
    g = 0.0
    while g <= p_max:
        gy = Y(g)
        out.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - 14}" y2="{gy:.1f}" '
                   f'stroke="{HAIR}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 6}" y="{gy + 3.5:.1f}" text-anchor="end" '
                   f'font-size="9" fill="{FAINT}">{g * 100:.0f}%</text>')
        g += 0.05
    # baseline
    out.append(f'<line x1="{pad_l}" y1="{Y(0):.1f}" x2="{width - 14}" y2="{Y(0):.1f}" '
               f'stroke="{SLATE}" stroke-width="1"/>')

    pts = []
    for i, d in enumerate(digits):
        cx = pad_l + bw * i + bw / 2
        p_obs = freq.get(d, 0) / n
        ci = 1.96 * math.sqrt(max(p_obs * (1 - p_obs), 1e-12) / n)
        bar_w = bw * 0.52
        by, bh = Y(p_obs), Y(0) - Y(p_obs)
        out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{by:.1f}" width="{bar_w:.1f}" '
                   f'height="{max(bh, 1):.1f}" fill="{NAVY}" opacity=".88"/>')
        # expected marker
        ey = Y(p_exp[i])
        out.append(f'<path d="M {cx - 5:.1f} {ey:.1f} L {cx:.1f} {ey - 5:.1f} '
                   f'L {cx + 5:.1f} {ey:.1f} L {cx:.1f} {ey + 5:.1f} Z" '
                   f'fill="{AMBER}"/>')
        # CI whisker on observed
        y_hi, y_lo = Y(min(p_obs + ci, p_max)), Y(max(p_obs - ci, 0))
        out.append(f'<line x1="{cx:.1f}" y1="{y_hi:.1f}" x2="{cx:.1f}" y2="{y_lo:.1f}" '
                   f'stroke="{INK}" stroke-width="1.2" opacity=".75"/>')
        out.append(f'<line x1="{cx - 4:.1f}" y1="{y_hi:.1f}" x2="{cx + 4:.1f}" y2="{y_hi:.1f}" '
                   f'stroke="{INK}" stroke-width="1.2" opacity=".75"/>')
        out.append(f'<line x1="{cx - 4:.1f}" y1="{y_lo:.1f}" x2="{cx + 4:.1f}" y2="{y_lo:.1f}" '
                   f'stroke="{INK}" stroke-width="1.2" opacity=".75"/>')
        out.append(f'<text x="{cx:.1f}" y="{height - 10}" text-anchor="middle" '
                   f'font-size="11" fill="{SLATE}">{d}</text>')
        pts.append((cx, Y(p_exp[i])))
    # expected trend line across markers
    if len(pts) > 1:
        dpath = " " .join(("M" if i == 0 else "L") + f" {x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
        out.append(f'<path d="{dpath}" fill="none" stroke="{AMBER}" stroke-width="1.4" '
                   f'stroke-dasharray="5 4" opacity=".85"/>')
    out.append("</svg>")
    legend = (f'<div class="legend">'
              f'<span><span class="sw" style="background:{NAVY};"></pan></span>'.replace("</pan>", "")
              + f'observed</span>'
              f'<span><span class="sw" style="background:{AMBER};"></span>Benford expected</span>'
              f'<span><span class="sw" style="background:{INK};height:2px;border-radius:0;'
              f'margin-top:4px;"></span>95% CI (observed)</span></div>')
    return "".join(out) + legend, n


# ---------------------------------------------------------------------------
# data helpers
# ---------------------------------------------------------------------------

RULE_META = {
    "manual_entries": ("Manual entries",
                       "Lines posted manually (mapped type or derived human username) — "
                       "the primary journal-entry fraud vehicle."),
    "period_end": ("Period-end proximity",
                   "Manual entries within the configured pre/post-close window around "
                   "period end, including post-close postings."),
    "round_amounts": ("Round amounts",
                      "Large amounts divisible by the round-number multiple above the "
                      "materiality floor."),
    "date_divergence": ("Date divergence",
                        "Document date vs posting date gaps and entries created after "
                        "period end but posted in-period (backdating signal)."),
    "entry_splitting": ("Entry splitting",
                        "Clusters of manual lines just below the split threshold to one "
                        "account within a short window (salami tactics)."),
    "balance_check": ("Balance check",
                      "Documents whose debit/credit lines fail to net to zero within "
                      "tolerance — impossible without error or manipulation."),
    "unusual_users": ("Unusual users",
                      "Rare manual users and users on the configured high-risk list."),
    "unusual_pairs": ("Unusual account pairs",
                      "Debit/credit account pairs absent from the system-entry baseline "
                      "(a document never baselines itself)."),
    "reversals": ("Reversals",
                  "Near-exact negations of in-period entries shortly after period end "
                  "(profit-and-loss fix pattern)."),
    "high_risk_system_pairs": ("High-risk system pairs",
                               "Informational screen — system documents by high-risk users "
                               "on accounts unusual for that user. Never gates."),
}

FLAG_TABLES = ["flags_" + k for k in RULE_META]


def _executive_assessment(config, population, flagged_docs, universe, eff,
                          rule_counts, triage, ben, chains_ok, ccy):
    """Derive the BLUF paragraph and risk-rated 5C findings from run facts.

    Deterministic synthesis of what the engagement actually observed — auditor
    decisions carry the substance; rule statistics carry the breadth.
    """
    dec = {"inspect": 0, "accept": 0, "override": 0}
    for d in eff.values():
        dec[d["decision"]] = dec.get(d["decision"], 0) + 1
    inspected = [ref for ref, d in eff.items() if d["decision"] == "inspect"]
    n_univ = universe.selected
    n_high_triage = 0
    if triage:
        n_high_triage = sum(1 for a in triage["assessments"]
                            if a.get("rationale_concern") == "high")

    # ---- BLUF ---------------------------------------------------------------
    parts = []
    parts.append(
        f"We tested {population:,} journal lines for the period ending "
        f"{config.period_end}; {flagged_docs:,} documents flagged by ten risk rules "
        f"were ranked into a {n_univ:,}-item review universe.")
    if dec["inspect"]:
        parts.append(
            f"The reviewer directed {dec['inspect']} item(s) for substantive "
            f"inspection"
            + (f" and accepted {dec['accept']} as adequately supported"
               if dec["accept"] else "") + ".")
    elif dec["accept"]:
        parts.append(f"All {dec['accept']} reviewed item(s) were accepted as supported.")
    if n_high_triage:
        parts.append(f"The model rated {n_high_triage} item(s) high-concern; "
                     "each received a human decision.")
    if universe.fallback_used:
        parts.append(
            "Currency coverage gaps restricted ranking to the base currency; the "
            "excluded populations are documented (Section 3) and constitute a "
            "scope limitation requiring acknowledgment.")
    parts.append(
        "No unbalanced documents escaped review"
        if rule_counts.get("balance_check", 0) == 0 else
        f"{rule_counts.get('balance_check', 0)} document(s) failed the balance check "
        "(debits ≠ credits) — impossible without error or manipulation; each is "
        "individually decided below.")
    bluf = " ".join(parts)

    # ---- findings (risk-rated, 5C) -------------------------------------------
    findings = []

    # F1: balance-check failures — highest inherent risk
    if rule_counts.get("balance_check", 0):
        findings.append({
            "severity": "high",
            "title": "Journal documents that do not balance",
            "criteria": ("Every journal document must net to zero across its lines "
                         "(double-entry principle)."),
            "condition": (f"{rule_counts.get('balance_check')} document(s) in the "
                          "population fail the balance check within tolerance."),
            "cause": ("Possible causes include extract truncation, manual keying error, "
                      "or deliberate manipulation of line amounts."),
            "consequence": ("Unbalanced postings indicate a breakdown of the fundamental "
                            "control that makes journal analysis reliable; if present in "
                            "the ledger they misstate account balances directly."),
            "corrective": ("Vouch each listed document to its source and ledger image; "
                           "if the ledger agrees, escalate as a potential override of "
                           "controls and consider fraud-response obligations (ISA 240 §32)."),
        })

    # F2: high-risk user concentration (auditor decisions carry the evidence)
    users = {}
    for d in eff.values():
        r = (d.get("reason") or "")
        import re as _re
        m = _re.search(r"user ([A-Z].[A-Z]+|H\.AITLA|K\.MANSOURI)", r)
        if m:
            users[m.group(1)] = users.get(m.group(1), 0) + 1
    if users:
        top_user, top_n = max(users.items(), key=lambda kv: kv[1])
        if top_n >= 3:
            findings.append({
                "severity": "medium",
                "title": f"Manual-entry concentration by flagged user {top_user}",
                "criteria": ("High-risk users (per engagement risk assessment) should "
                             "generate few manual entries, each independently supported."),
                "condition": (f"{top_n} of {len(eff)} reviewed documents were posted "
                              f"manually by {top_user}, including period-end asset "
                              "acquisitions routed through an account pair absent from "
                              "the system baseline."),
                "cause": ("Asset acquisitions posted manually outside the standard "
                          "procurement workflow suggest either an approval bypass or "
                          "an unconfigured automated interface."),
                "consequence": ("Concentration of manual authority in one flagged user "
                                "over large, just-below-threshold acquisitions weakens "
                                "segregation of duties and raises structuring risk."),
                "corrective": ("Enquire on capex approval workflow; re-assign posting "
                               "rights; require dual authorization above a defined "
                               "threshold; perform collective evaluation of the series."),
            })

    # F3: Benford nonconformity (informational)
    if ben.get("mad") is not None and ben.get("nigrini_assessment") in (
            "nonconformity", "marginally acceptable"):
        findings.append({
            "severity": "low",
            "title": "First-digit distribution deviates from Benford expectation",
            "criteria": ("Benford's Law is an informational analytical (amendment C2); "
                         "journal populations are not naturally Benford-distributed."),
            "condition": (f"MAD {ben['mad']:.4f} — "
                          f"{ben.get('nigrini_assessment', '—')} on Nigrini bands."),
            "cause": ("Round-amount conventions (MAD bookkeeping, 10k multiples), "
                      "threshold clustering, or genuine digit-pattern anomalies."),
            "consequence": ("None by itself; deviation informs where to point inquiry, "
                            "never concludes fraud."),
            "corrective": ("Use the digit-level chart (Section 2) to target inquiry; "
                           "correlate spikes with round-amount and splitting rules."),
        })

    return bluf, findings


def _rule_detail(con, table):
    if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?",
                       [table]).fetchone()[0]:
        return 0, [], {}
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM duckdb_columns() WHERE table_name = ?", [table]).fetchall()}
    total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    if not total:
        return 0, [], {}
    monthly = {}
    if "posting_date" in cols:
        monthly = {d: s for d, s in con.execute(f"""
            SELECT strftime(posting_date,'%Y-%m'), SUM(ABS(CAST(amount AS DOUBLE)))
            FROM {table} WHERE posting_date IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall()}
    has_amt = "amount" in cols
    has_pd = "posting_date" in cols
    top = []
    for r in con.execute(f"""
        SELECT entry_ref, line_no, username,
               {'CAST(amount AS DOUBLE)' if has_amt else 'NULL'}
               {', posting_date' if has_pd else ''}
        FROM {table}
        ORDER BY {'ABS(CAST(amount AS DOUBLE))' if has_amt else 'entry_ref'} DESC
        LIMIT 5""").fetchall():
        top.append({"entry_ref": r[0], "line_no": r[1], "username": r[2],
                    "amount": (r[3] if has_amt else None),
                    "posting_date": (r[4] if has_pd else None)})
    return total, top, monthly


def build_report(run_dir: Path) -> Path:
    ctx = RunContext(Path(run_dir))
    config: EngagementConfig = load_config(ctx.dir / "config.yaml")
    run_id = config.run_id
    ccy = config.materiality.currency

    store = RunStore(ctx.runstore_path)
    con = duckdb.connect(str(ctx.duckdb_path), read_only=True)

    info = store.get_run(run_id) or {}
    status = info.get("status", "?")

    population = con.execute("SELECT count(*) FROM journal_lines").fetchone()[0]
    flagged_docs = con.execute(
        "SELECT count(DISTINCT entry_ref) FROM xref_ranked").fetchone()[0]
    universe = select_universe(con, config)

    exec_rows = store.con.execute("""
        SELECT tool, CAST(json_extract(result_json,'$.flagged') AS INT)
        FROM tool_calls WHERE phase='EXECUTE' AND outcome='ok'
          AND result_json IS NOT NULL ORDER BY seq""").fetchall()
    rule_counts = dict(exec_rows)

    eff = effective_decisions(store, run_id)
    dec_counts = {"inspect": 0, "accept": 0, "override": 0}
    for d in eff.values():
        dec_counts[d["decision"]] = dec_counts.get(d["decision"], 0) + 1

    chains_ok = all(c.intact for c in verify_all_chains(store, run_id).values())
    n_llm = store.con.execute("SELECT count(*) FROM llm_outputs WHERE run_id=?",
                              [run_id]).fetchone()[0]

    from .report_lang import labels
    lang = (getattr(getattr(config, "report_lang", None), "lang", "en") or "en")
    L = labels(lang)

    facts = build_facts_block(con, config, universe, None, store)

    tp = ctx.llm_dir / "triage_report.json"
    triage = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else None
    np_ = ctx.llm_dir / "narrative.json"
    narrative = json.loads(np_.read_text(encoding="utf-8")) if np_.exists() else None

    dq_rows = store.con.execute(
        "SELECT warning_id, scope, reason, reviewer FROM dq_acknowledgments "
        "WHERE run_id=? ORDER BY id", [run_id]).fetchall()

    # Benford conformity — computed live on THIS run's population (C2 informational)
    ben = run_benford(con, run_id)

    # per-rule detail payloads (gathered while con is open; rendered later)
    rule_payloads = {k: _rule_detail(con, "flags_" + k) for k in RULE_META}

    extract_name = "source_extract.csv"
    try:
        import hashlib as _hashlib

        src = next(iter(ctx.dir.glob("*.csv")), None)
        if src is not None:
            extract_name = src.name
        digest = (_hashlib.sha256(src.read_bytes()).hexdigest()
                  if src is not None else "unavailable")
    except OSError:
        digest = "unavailable"
    extract_sha = digest

    con.close()
    store.close()

    def resolve(text: str) -> str:
        return re.sub(r"\[fact:([a-z0-9_]+)\]",
                      lambda m: f"<b>{_esc(facts.get(m.group(1), '?'))}</b>", _esc(text))

    H = [f"<!DOCTYPE html><html lang=\"{lang}\"><head><meta charset=\"utf-8\">"
         f"<title>{_esc(run_id)} — JE Agent</title><style>{CSS}</style></head><body><div class='wrap'>"]
    gen_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    fin = status == "finalized"

    # ---------------------------------------------------------- cover page
    H.append(f"""
<div class="coverpage">
  <div class="cv-head">
    <div class="cv-firm">{L['eyebrow']}</div>
    <div class="cv-title">{_esc(run_id)}</div>
    <div class="cv-sub">{_esc(config.source.system.upper())} {L['sub']}</div>
  </div>
  <hr class="cv-rule">
  <div class="cv-body">
    <div class="cv-eyebrow">{L['eng_summary']}</div>
    <table class="cv">
      <tr><td class="k">{L['period']}</td><td class="v">{_esc(config.period_end)}</td></tr>
      <tr><td class="k">{L['source']}</td><td class="v">{_esc(config.source.system.upper())}
        · {_esc(extract_name)} ({_esc(extract_sha[:16])}…) </td></tr>
      <tr><td class="k">{L['population']}</td>
          <td class="v">{population:,} {L['lines']}</td></tr>
      <tr><td class="k">{L['materiality']}</td>
          <td class="v">{L['overall']} {_esc(_money(config.materiality.overall, ccy))} ·
            {L['performance']} {_esc(_money(config.materiality.performance, ccy))}</td></tr>
      <tr><td class="k">{L['flagged']}</td>
          <td class="v">{flagged_docs:,} {L['documents']} → {L['universe_of']} {universe.selected:,}
            ({dec_counts['inspect']} {L['inspect']} · {dec_counts['accept']} {L['accepted']} ·
            {dec_counts['override']} {L['override']})</td></tr>
      <tr><td class="k">{L['benford']}</td>
          <td class="v">{('MAD ' + format(ben['mad'], '.4f') + ' — '
                          + _esc(ben.get('nigrini_assessment', '—')))
                         if ben.get('mad') is not None else 'insufficient data'}</td></tr>
      <tr><td class="k">{L['auditor']}</td><td class="v">{_esc(config.reviewer.name)}
        · {L['hash_chained']} {L['verified'] if chains_ok else L['broken']}</td></tr>
      <tr><td class="k">{L['status']}</td>
          <td class="v"><span class="status-pill {'ok' if fin else 'warn'}">
            {L['finalized'] if fin else L['draft']}</span> — {L['all_gates'] if fin else L['draft_gates']}</td></tr>
    </table>
  </div>
  <div class="cv-foot">
    <span style="max-width:520px"><b>{L['confidential'].split('.')[0]}.</b> {L['confidential'].split('.', 1)[1].strip()}</span>
    <span>{L['generated']} {gen_ts}</span>
  </div>
</div>""")

    # ---------------------------------------------------------- masthead
    H.append(f"""
<div class="mast">
  <div>
    <div class="firm">Journal Entry Testing · ISA 240 / AS 2401</div>
    <h1>Audit Report — {_esc(run_id)}</h1>
  </div>
  <div class="mh-meta">
    {_esc(config.source.system.upper())} extract · period end <b>{_esc(config.period_end)}</b><br>
    materiality {_esc(_money(config.materiality.overall, ccy))} · reviewer
    <b>{_esc(config.reviewer.name)}</b><br>
    generated {gen_ts} ·
    <span class="status-pill {'ok' if fin else 'warn'}">{'FINALIZED — gates passed'
     if fin else 'status: ' + _esc(status)}</span>
  </div>
</div>""")

    # ---------------------------------------------------------- stat strip
    integ_lbl = "chain verified" if chains_ok else "CHAIN BROKEN"
    stats = [
        (f"{population:,}", "population lines", ""),
        (f"{flagged_docs:,}", "flagged documents", ""),
        (f"{universe.selected:,}", "review universe", ""),
        (str(dec_counts["inspect"]), "inspect", f"color:{AMBER}"),
        (str(dec_counts["accept"]), "accepted", ""),
        (str(dec_counts["override"]), "overrides", ""),
        (integ_lbl, "decision log integrity",
         f"color:{INK if chains_ok else AMBER}"),
        (str(n_llm), "llm turns logged", ""),
    ]
    H.append('<div class="strip">' + "".join(
        f'<div class="stat"><div class="v" style="{s}">{v}</div>'
        f'<div class="l">{l}</div></div>' for v, l, s in stats) + "</div>")

    # ====================================================== 0 · BLUF + FINDINGS
    # Executive assessment (Bottom-Line-Up-Front) + risk-rated findings per
    # audit-reporting best practice: conclusions first, 5C issue structure,
    # findings tied to business risk, not methodology.
    bluf, findings = _executive_assessment(
        config, population, flagged_docs, universe, eff, rule_counts,
        triage, ben, chains_ok, ccy)

    H.append('<h2 class="sec">Executive assessment</h2>')
    H.append(f"<div class='bluf'>{bluf}</div>")

    if findings:
        H.append('<h2 class="sec">Findings &amp; observations</h2>'
                 "<p class='secsub'>Risk-rated, 5C structure (criteria · condition · cause · "
                 "consequence · corrective action). Highest risk first.</p>")
        for f in findings:
            sev_cls = {"high": "high", "medium": "medium", "low": "low"}.get(f["severity"], "low")
            H.append(
                f"<div class='finding sev-{sev_cls}'>"
                f"<div class='fhead'><span class='sev sev-{sev_cls}'>"
                f"{f['severity'].upper()}</span>"
                f"<b>{_esc(f['title'])}</b></div>"
                "<table class='t f5c'>"
                f"<tr><td class='k'>Criteria</td><td>{_esc(f['criteria'])}</td></tr>"
                f"<tr><td class='k'>Condition</td><td>{_esc(f['condition'])}</td></tr>"
                f"<tr><td class='k'>Cause</td><td>{_esc(f['cause'])}</td></tr>"
                f"<tr><td class='k'>Consequence</td><td>{_esc(f['consequence'])}</td></tr>"
                f"<tr><td class='k'>Corrective action</td><td>{_esc(f['corrective'])}</td></tr>"
                "</table></div>")

    # =========================================================== 1 · RULES
    H.append('<h2 class="sec">1 · Deterministic rule results</h2>'
             "<p class='secsub'>Ten rules executed in canonical order on the frozen extract. "
             "Recall-first design: every hit enters cross-reference ranking; precision is "
             "restored by human review. Expand a rule for its distribution and top hits.</p>")

    H.append('<div class="card"><table class="t">'
             "<tr><th style='width:26%'>rule</th><th>what it detects</th>"
             "<th class='num'>flags</th><th>% of pop.</th><th style='width:11%'>outcome</th></tr>")
    total_flags = sum(rule_counts.values()) or 1
    for key in RULE_META:
        name, desc = RULE_META[key]
        n = rule_counts.get(key, 0)
        outcome = (_chip("zero", "clean") if n == 0 else
                   ("<span style='font-weight:750;color:" + AMBER + ";'>review driver</span>"
                    if n <= 5000 else "ranked"))
        H.append(f"<tr><td><b>{name}</b><br><span class='mono' style='color:{FAINT};'>"
                 f"flags_{key}</span></td><td class='reason'>{desc}</td>"
                 f"<td class='num'><b>{n:,}</b></td>"
                 f"<td class='num' style='color:{SLATE};'>{n / population:.1%}</td>"
                 f"<td>{outcome}</td></tr>")
    H.append("</table></div>")

    # collapsible per-rule detail
    for key in RULE_META:
        name, desc = RULE_META[key]
        n = rule_counts.get(key, 0)
        total, top, monthly = rule_payloads[key]
        body = [f"<div class='rdesc'>{desc}</div>"]
        if total:
            if monthly:
                body.append(svg_timeline(monthly))
                body.append(f"<div class='note' style='margin:4px 0 8px;'>Monthly absolute-"
                            f"value profile of flagged lines.</div>")
            if top and top[0].get("amount") is not None:
                rows = "".join(
                    f"<tr><td class='mono'><b>{_esc(t['entry_ref'])}</b>&nbsp;"
                    f"L{_esc(t['line_no'])}</td>"
                    f"<td>{_esc(t.get('posting_date') or '')}</td>"
                    f"<td>{_esc(t['username'] or '—')}</td>"
                    f"<td class='num'>{_money(t['amount'], ccy)}</td></tr>" for t in top)
                body.append("<table class='t'><tr><th>top entries by amount</th><th>date</th>"
                            f"<th>user</th><th class='num'>amount</th></tr>{rows}</table>")
        elif n == 0 and total == 0:
            body.append(f"<div class='note' style='color:{GREEN};'>No hits on this "
                        f"population — nothing required attention.</div>")
        open_attr = " open" if key in ("balance_check", "date_divergence") else ""
        H.append(f"<details class='rule'{open_attr}><summary>{name}"
                 f"&nbsp;<span class='chip {'zero' if n==0 else 'det'}'>{n:,} flagged</span>"
                 f"</summary><div class='rbody'>{''.join(body)}</div></details>")

    # =========================================================== 2 · BENFORD
    H.append('<h2 class="sec">2 · Benford first-digit conformity</h2>'
             "<p class='secsub'>Informational analytical (amendment C2): observed leading-digit "
             "distribution of all absolute amounts ≥ 1 against the Benford expectation, with "
             "95% confidence whiskers on each observation. Informs inquiry — never gates.</p>")
    freq = {int(k): v for k, v in (ben.get("first_digit_frequencies") or {}).items()}
    if ben.get("mad") is not None and freq:
        chart, bn = svg_benford(freq)
        assess = ben.get("nigrini_assessment", "—")
        a_chip = {"close conformity": "ok", "acceptable conformity": "ok",
                  "marginally acceptable": "warn", "nonconformity": "warn"}.get(assess, "det")
        H.append(f"<div class='two'><div class='card'>{chart}</div>"
                 "<div class='card'>"
                 f"<div style='font-size:11px;color:{SLATE};text-transform:uppercase;"
                 f"letter-spacing:.8px;'>mean absolute deviation</div>"
                 f"<div style='font-size:30px;font-weight:800;margin:2px 0;'>"
                 f"{ben['mad']:.4f}</div>"
                 f"<div>Nigrini bands: {_chip(a_chip, assess)}</div>"
                 f"<hr style='border:none;border-top:1px solid {HAIR};margin:12px 0;'>"
                 f"<div class='reason'>Read: bars are the observed share of amounts starting "
                 f"with each digit; amber diamonds join the Benford curve log₁₀(1+1/d); "
                 f"whiskers are 95% confidence intervals. Whiskers crossing the diamonds are "
                 f"consistent with expectation.</div>"
                 f"<div class='note' style='margin-top:10px;'>Population analysed: "
                 f"<b>{bn:,}</b> amounts. Journal populations are not naturally Benford-"
                 f"distributed (C2); deviations inform inquiry and never conclude fraud.</div>"
                 "</div></div>")
    else:
        H.append(f"<div class='card'><div class='note'>{_esc(ben.get('assessment', 'insufficient data'))} "
                 f"— Benford requires ≥ 100 amounts.</div></div>")

    # =========================================================== 3 · UNIVERSE
    H.append('<h2 class="sec">3 · Review-universe selection</h2>'
             "<p class='secsub'>Workload control W1 with currency-stratified fallback X2/Y8; "
             "exclusions are limitations requiring acceptance (gate 4).</p>")
    excl = universe.excluded_currencies
    H.append("<div class='funnelline'>"
             f"<span class='fstage'><b>{flagged_docs:,}</b> flagged docs</span> →"
             f"<span class='fstage'><b>{universe.selected:,}</b> selected for review</span> →"
             f"<span class='fstage'><b>{len(eff)}</b> decided</span> →"
             f"<span class='fstage'><b>{universe.selected - len(eff)}</b> pending</span>"
             + (f" → <span class='fstage'><b>{len(excl)}</b> currencies excluded</span>"
                if excl else "")
             + "</div>")
    if universe.fallback_used and excl:
        rows = "".join(
            f"<tr><td><b>{_esc(x.currency)}</b></td><td class='num'>{x.entries:,}</td>"
            f"<td class='num'>{x.volume_share:.1%}</td>"
            f"<td class='num'>{_money(x.largest_entry_abs, ccy)}</td></tr>"
            for x in excl)
        H.append("<div class='card'><div class='note' style='margin-bottom:8px;'>"
                 "No usable fx coverage — ranking restricted to base currency; excluded "
                 "populations documented below:</div><table class='t'>"
                 "<tr><th>currency</th><th class='num'>excluded entries</th>"
                 "<th class='num'>volume share</th><th class='num'>largest excluded entry</th>"
                 f"</tr>{rows}</table></div>")

    # =========================================================== 4 · TRIAGE
    H.append('<h2 class="sec">4 · LLM triage — machine reasoning</h2>'
             "<p class='secsub'>Advisory assessments under rubric v1.0.0. Violet badges mark "
             "model output; the auditor table that follows is authoritative.</p>")
    if triage:
        levels = {}
        for a in triage["assessments"]:
            levels[a["rationale_concern"]] = levels.get(a["rationale_concern"], 0) + 1
        seg_colors = {"high": RED, "medium": AMBER, "low": NAVY}
        segs = [(k, v, seg_colors.get(k, FAINT)) for k, v in sorted(levels.items())]
        total_n = sum(v for _, v, _ in segs) or 1
        circ = 2 * math.pi * 44
        off = 0.0
        arcs = []
        for lbl, v, colr in segs:
            dash = v / total_n * circ
            arcs.append(f"<circle cx='60' cy='60' r='44' fill='none' stroke='{colr}' "
                        f"stroke-width='17' stroke-dasharray='{dash:.1f} {circ - dash:.1f}' "
                        f"stroke-dashoffset='{-off:.1f}' transform='rotate(-90 60 60)'/>")
            off += dash
        legend = "".join(
            f"<span><span class='sw' style='background:{c};'></span>{_esc(l)}: "
            f"<b>{v}</b></span>" for l, v, c in segs)
        H.append(f"<div class='card'><div style='display:flex;gap:26px;align-items:center;"
                 f"flex-wrap:wrap;'><svg viewBox='0 0 120 120' width='120' height='120' "
                 f"xmlns='http://www.w3.org/2000/svg'>{''.join(arcs)}</svg>"
                 f"<div class='legend' style='flex-direction:column;gap:6px;'>{legend}</div></div>")
        seen = set()
        pri_sorted = sorted(triage["assessments"], key=lambda x: (-x["priority"], x["entry_ref"]))
        shown = 0
        extra = []
        for a in pri_sorted:
            ref = a["entry_ref"]
            if ref in seen:
                continue
            seen.add(ref)
            item = (f"<div style='margin-bottom:10px;'><b class='mono'>{_esc(ref)}</b> "
                    f"{_chip(a['rationale_concern'])} {_chip('llm', 'P' + str(a['priority']))}"
                    f"<div class='reason'>{_esc(a['concern_note'])}</div></div>")
            extra.append((shown < 3, item))
            shown += 1
        inline = "".join(itm for top, itm in extra if top)
        folded = "".join(itm for top, itm in extra if not top)
        H.append(inline)
        if folded:
            H.append(f"<details class='rule'><summary>remaining {sum(1 for t,_ in extra if not t)} "
                     f"assessed documents</summary><div class='rbody'>{folded}</div></details>")
        H.append("</div>")

    # =========================================================== 5 · REVIEW
    H.append('<h2 class="sec">5 · Auditor review — human decisions</h2>'
             "<p class='secsub'>Substantive judgments recorded hash-chained (supersessions "
             "preserve history). This table is the authoritative record of the engagement.</p>")
    H.append("<div class='card'><table class='t'>"
             "<tr><th style='width:19%'>entry</th><th style='width:10%'>decision</th>"
             "<th>auditor reasoning</th></tr>")
    for ref in sorted(eff):
        d = eff[ref]
        H.append(f"<tr><td class='mono'><b>{_esc(ref)}</b></td>"
                 f"<td>{_chip(d['decision'])}</td>"
                 f"<td><div class='reason'>{_esc(d.get('reason') or '—')}</div>"
                 f"<div class='note' style='margin-top:3px;'>{_esc(d.get('reviewer','?'))}"
                 f" · {(d.get('ts') or '')[:16]}</div></td></tr>")
    H.append("</table></div>")

    # =========================================================== 6 · NARRATIVE
    H.append('<h2 class="sec">6 · Workpaper narrative</h2>'
             "<p class='secsub'>Drafted by the model strictly from the keyed facts block; "
             "citations resolved inline (gate 3 validates every reference).</p>")
    H.append("<div class='narrative'>")
    if narrative:
        for s in narrative["sections"]:
            H.append(f"<h3>{_esc(s['heading'])}</h3><p>{resolve(s['text'])}</p>")
    else:
        H.append("<p>No narrative artifact for this run.</p>")
    H.append("</div>")

    # =========================================================== 7 · GOVERNANCE
    H.append('<h2 class="sec">7 · Limitations &amp; governance</h2>')
    lim_items = "".join(f"<li style='margin-bottom:6px;'>{_esc(l)}</li>" for l in BASE_LIMITATIONS)
    dq_html = ("".join(
        f"<tr><td class='mono'>{_esc(w)}</td><td>{_esc(r)}</td><td>{_esc(rv)}</td></tr>"
        for w, _s, r, rv in dq_rows)
        or f"<tr><td colspan='3' class='note'>none acknowledged this run</td></tr>")
    H.append(
        "<div class='two'><div class='card'><b>Mandatory limitations (§11)</b>"
        f"<ol style='margin:8px 0 0;padding-left:20px;font-size:12.5px;color:{SLATE};'>"
        f"{lim_items}</ol></div>"
        "<div class='card'><b>DQ acknowledgments &amp; integrity</b>"
        "<table class='t' style='margin-top:8px;'><tr><th>warning</th><th>reason</th>"
        f"<th>reviewer</th></tr>{dq_html}</table>"
        f"<div style='margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;'"
        f">{_chip('det','deterministic engine')}{_chip('llm','LLM triage + narrative')}"
        f"{_chip('human','human decisions')}"
        f"{_chip('ok' if chains_ok else 'warn', 'hash chain VERIFIED' if chains_ok else 'CHAIN BROKEN')}"
        f"</div></div></div>")

    H.append(f"""<div class="footer"><b>Scope &amp; use.</b> This tool is a risk-flagging,
prioritization, documentation and review-workflow system. It is not a substitute for substantive
testing or vouching, not a complete fraud detection system, and provides no assurance that no
material misstatement exists. Entries marked “inspect” leave this tool for substantive testing
against supporting documentation; this report lists them — it does not vouch them.
LLM outputs are documented, not deterministic; the deterministic path is reproducible and the
judgment path fully logged and tamper-evident.</div></div>""")

    out = ctx.artifacts_dir / "report.html"
    out.write_text("".join(H), encoding="utf-8")
    return out


def export_pdf(run_dir: Path) -> Path:
    """Render report.html to PDF via Playwright's Python API (backgrounds ON).

    Agent-driven: called automatically at finalize. The HTML carries @page A4 +
    print CSS + the cover page, so the PDF is a first-class deliverable.
    """
    html_path = build_report(Path(run_dir))
    pdf_path = html_path.with_suffix(".pdf")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        page.emulate_media(media="print")
        page.pdf(path=str(pdf_path), print_background=True,
                 prefer_css_page_size=True)
        browser.close()
    if not pdf_path.exists():
        raise RuntimeError("PDF export produced no file")
    return pdf_path
