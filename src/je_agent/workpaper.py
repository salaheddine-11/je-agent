"""Workpaper writer — the final audit deliverable (DESIGN §8, §11).

Multi-sheet xlsx: Summary | Narrative | Flagged Entries (top) | Scope & Limitations |
DQ Appendix | AI Governance. Every number rendered from the facts block; narrative
citations already resolved by the caller.
"""

from __future__ import annotations

from pathlib import Path

import xlsxwriter

from .document import BASE_LIMITATIONS


def write_workpaper(path: Path, wp: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path))

    title_fmt = wb.add_format({"bold": True, "font_size": 14})
    head_fmt = wb.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "#FFFFFF",
                              "text_wrap": True, "valign": "top"})
    cell_fmt = wb.add_format({"text_wrap": True, "valign": "top"})
    kv_key_fmt = wb.add_format({"bold": True, "valign": "top"})
    warn_fmt = wb.add_format({"font_color": "#B45309", "text_wrap": True, "valign": "top"})

    def _sheet(name, widths=None):
        ws = wb.add_worksheet(name[:31])
        if widths:
            for c, w in enumerate(widths):
                ws.set_column(c, c, w)
        return ws

    # ------------------------------------------------------------------ Summary
    ws = _sheet("Summary", [34, 60])
    ws.write(0, 0, wp["title"], title_fmt)
    ws.write(1, 0, "Period end", kv_key_fmt); ws.write(1, 1, wp["period_end"])
    r = 3
    ws.write(r, 0, "Key facts (all numbers trace to the run store)", head_fmt)
    ws.write(r, 1, "", head_fmt)
    for k in sorted(wp["facts"]):
        r += 1
        ws.write(r, 0, k, kv_key_fmt)
        ws.write(r, 1, wp["facts"][k])

    # ---------------------------------------------------------------- Narrative
    ws = _sheet("Narrative", [28, 110])
    ws.write(0, 0, "Narrative (LLM-drafted, human-reviewed; citations resolved)", title_fmt)
    r = 2
    for s in wp.get("narrative_sections", []):
        ws.write(r, 0, s["heading"], head_fmt)
        ws.write(r, 1, s["text"], cell_fmt)
        r += 2
    if not wp.get("narrative_sections"):
        ws.write(2, 0, "(no narrative artifact)", warn_fmt)

    # ------------------------------------------------------- Scope & Limitations
    ws = _sheet("Scope&Limitations", [6, 130])
    ws.write(0, 0, "#", head_fmt)
    ws.write(0, 1, "Mandatory scope & limitations (§11)", head_fmt)
    for i, lim in enumerate(wp["scope_and_limitations"]["base"], start=1):
        ws.write(i, 0, i)
        ws.write(i, 1, lim, cell_fmt)
    r = len(wp["scope_and_limitations"]["base"]) + 2
    ws.write(r, 0, "Accepted dynamic limitations", head_fmt)
    ws.write(r, 1, "", head_fmt)
    dyn = wp["scope_and_limitations"].get("dynamic_accepted") or []
    if not dyn:
        r += 1
        ws.write(r, 1, "(none)", cell_fmt)
    for d in dyn:
        r += 1
        ws.write(r, 1, d, cell_fmt)

    # -------------------------------------------------------------- DQ Appendix
    ws = _sheet("DQ Appendix", [30, 30, 70, 20])
    headers = ["warning_id", "scope", "reason", "reviewer"]
    for c, h in enumerate(headers):
        ws.write(0, c, h, head_fmt)
    rows = wp.get("dq_appendix") or []
    for ri, row in enumerate(rows, start=1):
        for ci, v in enumerate(row):
            ws.write(ri, ci, str(v) if v is not None else "", cell_fmt)
    if not rows:
        ws.write(1, 0, "(no acknowledged DQ warnings)", cell_fmt)

    # ------------------------------------------------------------ AI Governance
    ws = _sheet("AI Governance", [34, 100])
    gov = wp["ai_governance"]
    ws.write(0, 0, "What produced this workpaper", title_fmt)
    pairs = [
        ("Deterministic contribution", gov.get("deterministic", "")),
        ("LLM contribution", gov.get("llm_contribution", "")),
        ("Human contribution", gov.get("human_contribution", "")),
        ("Decision-log integrity", "VERIFIED — hash chains intact"
         if gov.get("chain_integrity_verified") else "FAILED VERIFICATION"),
        ("Injection advisory caption",
         "Injection suspicion is an advisory technical signal. It does not by itself prove "
         "fraud. Evaluate the accounting substance."),
        ("PII residual risk",
         "Regex-class + redaction-term scrubbing of LLM-bound text only; originals never "
         "leave the run folder; cannot catch all sensitive prose."),
    ]
    for r, (k, v) in enumerate(pairs, start=2):
        ws.write(r, 0, k, kv_key_fmt)
        ws.write(r, 1, v, cell_fmt)

    wb.close()
    return path
