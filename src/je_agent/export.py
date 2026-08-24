"""Flagged-entries Excel export (Phase 1 §10.1 deliverable)."""

from __future__ import annotations

from pathlib import Path

import duckdb


def export_flagged_entries(con: duckdb.DuckDBPyConnection, out_path: Path) -> Path:
    """Write xref_ranked joined back to journal lines as a formatted Excel workbook."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = con.execute("""
        SELECT x.rules_hit,
               x.entry_ref,
               x.line_no,
               j.posting_date,
               j.username,
               j.is_manual,
               j.entry_type_source,
               j.account,
               j.amount,
               j.currency,
               j.description,
               j.source_doc,
               x.flag_reasons,
               x.selection_basis
        FROM xref_ranked x
        JOIN journal_lines j USING (entry_ref, line_no)
        ORDER BY x.rules_hit DESC, x.abs_amount DESC, x.entry_ref, x.line_no
    """).fetchall()

    import xlsxwriter

    wb = xlsxwriter.Workbook(str(out_path))
    ws = wb.add_worksheet("flagged_entries")

    header_fmt = wb.add_format({"bold": True, "bg_color": "#1F2937", "font_color": "#FFFFFF"})
    money_fmt = wb.add_format({"num_format": "#,##0.00"})
    ws.freeze_panes(1, 2)

    headers = [
        "rules_hit", "entry_ref", "line_no", "posting_date", "username", "is_manual",
        "entry_type_source", "account", "amount", "currency", "description",
        "source_doc", "flag_reasons", "selection_basis",
    ]
    for col, h in enumerate(headers):
        ws.write(0, col, h, header_fmt)

    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            if c == 8:
                ws.write_number(r, c, float(val), money_fmt)
            elif c == 3 and val is not None:
                ws.write(r, c, str(val))
            else:
                ws.write(r, c, val)

    widths = [10, 12, 8, 12, 12, 10, 16, 10, 12, 9, 40, 14, 60, 14]
    for c, w in enumerate(widths):
        ws.set_column(c, c, w)

    wb.close()
    return out_path
