"""Seeded synthetic CLEAN journal-entry generator for the JE Agent audit app.

Generates a balanced, routine-only JE population (no planted anomalies) with
deterministic output for a given --seed. Stdlib only.

Usage:
    python tests/fixtures/generate_clean.py --lines 10000 --seed 20260823 --out tests/fixtures/clean.csv
"""

import argparse
import csv
import os
import random
import sys
from collections import defaultdict
from datetime import date, timedelta

HEADER = ["ENTRY", "LINE", "POST_DATE", "ACCOUNT", "USER", "DESCR", "DOC", "AMOUNT", "CURRENCY", "ENTRY_TYPE"]
SYSTEM_USERS = {"SAPUSER", "WF-BATCH", "BATCHRUN", "INTERFACE_RFC"}
HUMAN_USERS = {"JDOE", "MARTIN_B", "SMITH_C", "JONES_M", "PEREZ_A"}
START_DATE = date(2026, 1, 5)
END_DATE = date(2026, 7, 15)
REV_DESCRS = ("Sales invoice", "Customer billing", "Billing document posting")
LINE_TOLERANCE = 8


def fmt_amount(cents):
    sign = "-" if cents < 0 else ""
    a = abs(cents)
    return "%s%d.%02d" % (sign, a // 100, a % 100)


def parse_cents(text):
    neg = text.startswith("-")
    body = text[1:] if neg else text
    whole, _, frac = body.partition(".")
    cents = int(whole or "0") * 100 + int((frac + "00")[:2])
    return -cents if neg else cents


def month_end(year, month):
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def generate(rng, total_lines):
    docs = []
    stats = defaultdict(lambda: [0, 0])

    def emit(pattern, d, user, etype, descr, doc, lines):
        docs.append({
            "seq": len(docs),
            "date": d,
            "user": user,
            "etype": etype,
            "descr": descr,
            "doc": doc,
            "pattern": pattern,
            "lines": lines,
        })
        s = stats[pattern]
        s[0] += 1
        s[1] += len(lines)

    dates = []
    d = START_DATE
    while d <= END_DATE:
        dates.append(d)
        d += timedelta(days=1)

    for m in range(1, 7):
        pd = date(2026, m, 26)
        gross_h = rng.randrange(1520, 2630)
        cuts = sorted(rng.sample(range(1, gross_h), 3))
        edges = [0] + cuts + [gross_h]
        parts = [(edges[i + 1] - edges[i]) * 100 for i in range(4)]
        parts.sort(reverse=True)
        gross_cents = gross_h * 100 * 100
        lines = [("5000", gross_cents)] + [("2100", -(p * 100)) for p in parts]
        emit("payroll", pd, "WF-BATCH", "system", "Payroll posting run %s" % pd.strftime("%Y-%m"),
             "PR-" + pd.strftime("%Y%m"), lines)

    for m in range(1, 8):
        rd = date(2026, m, 5)
        amt = 8500 * 100
        emit("rent", rd, "JDOE", "manual", "Monthly office rent",
             "RENT-" + rd.strftime("%Y%m"), [("6100", amt), ("1000", -amt)])

    for m in range(1, 8):
        ud = date(2026, m, 15)
        amt = rng.randint(880, 1320) * 100 + rng.randint(1, 99)
        emit("utilities", ud, "MARTIN_B", "manual", "Utility payment",
             "UTIL-" + ud.strftime("%Y%m"), [("6300", amt), ("1000", -amt)])

    dep_monthly = (45500000 - 1750000) // 120
    for m in range(1, 7):
        dd = date(2026, m, 28)
        emit("depreciation", dd, "SAPUSER", "system", "Monthly depreciation charge",
             "DEP-" + dd.strftime("%Y%m"), [("6200", dep_monthly), ("1590", -dep_monthly)])

    for m in range(1, 7):
        adate = month_end(2026, m) - timedelta(days=rng.randint(0, 3))
        amt = rng.randint(1400, 3800) * 100 + rng.randint(1, 99)
        ref = "ACCR-" + adate.strftime("%Y%m")
        emit("accruals", adate, "JDOE", "manual", "Period-end accrual",
             ref, [("6500", amt), ("2100", -amt)])
        rdate = date(2026, m + 1, 5)
        emit("accruals", rdate, "JDOE", "manual", "Accrual reversal",
             ref + "-REV", [("6500", -amt), ("2100", amt)])

    ic_seq = 0
    for d in dates:
        if rng.random() >= 0.22:
            continue
        ic_seq += 1
        amt = rng.randint(1600, 7400) * 100 + rng.randint(1, 99)
        emit("intercompany", d, "BATCHRUN", "system", "Intercompany settlement",
             "IC-%04d" % ic_seq, [("1400", amt), ("2050", -amt)])

    fixed_lines = sum(s[1] for s in stats.values())
    remaining = total_lines - fixed_lines
    if remaining < 60:
        raise ValueError(
            "--lines %d is too small: calendar-driven patterns already need %d lines" % (total_lines, fixed_lines))

    rev_budget = (remaining * 55) // 100
    rev_budget -= rev_budget % 2
    sup_budget = remaining - rev_budget

    used = 0
    day_i = 0
    inv_seq = 0
    while True:
        room = rev_budget - used
        if room < 2:
            break
        d = dates[day_i % len(dates)]
        day_i += 1
        if rng.random() < 0.05:
            continue
        k = min(rng.randint(6, 16), room // 2)
        for _ in range(k):
            inv_seq += 1
            amt = rng.randint(800, 8600) * 100 + rng.randint(1, 99)
            emit("revenue", d, "SAPUSER", "system", rng.choice(REV_DESCRS),
                 "INV-%06d" % inv_seq, [("1200", amt), ("4000", -amt)])
            used += 2

    sup_loop_budget = sup_budget - 3 if sup_budget % 2 else sup_budget
    used = 0
    day_i = 0
    exp_seq = 0
    while True:
        room = sup_loop_budget - used
        if room < 2:
            break
        d = dates[day_i % len(dates)]
        day_i += 1
        if rng.random() < 0.10:
            continue
        k = min(rng.randint(2, 9), room // 2)
        for _ in range(k):
            exp_seq += 1
            acct = rng.choice(("6000", "7000"))
            descr = "Travel expense claim" if acct == "7000" else "Office supplies purchase"
            amt = rng.randint(14, 470) * 100 + rng.randint(1, 99)
            emit("supplies_travel", d, rng.choice(sorted(HUMAN_USERS)), "manual", descr,
                 "EXP-%06d" % exp_seq, [(acct, amt), ("1000", -amt)])
            used += 2
    if sup_budget % 2 and sup_budget - used == 3:
        exp_seq += 1
        amt = rng.randint(40, 300) * 100 + rng.randint(1, 99)
        half = amt // 2
        emit("supplies_travel", dates[day_i % len(dates)], rng.choice(sorted(HUMAN_USERS)), "manual",
             "Office supplies purchase", "EXP-%06d" % exp_seq,
             [("6000", amt), ("6000", -half), ("1000", -(amt - half))])
        used += 3

    return docs, stats


def check_file(path, requested_lines):
    failures = []
    entries = {}
    total_rows = 0
    bad_type_users = set()
    bad_currency = 0
    out_of_range_dates = []

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header != HEADER:
            failures.append("bad header: %r" % (header,))
        for row in reader:
            if len(row) != len(HEADER):
                failures.append("malformed row: %r" % (row,))
                continue
            entry_id, line_s, post_s, _acct, user, _descr, _doc, amount_s, cur, etype = row
            total_rows += 1
            e = entries.setdefault(entry_id, {"sum": 0, "lines": [], "pairs": set(), "dates": []})
            try:
                e["sum"] += parse_cents(amount_s)
            except ValueError:
                failures.append("unparseable AMOUNT %r in %s" % (amount_s, entry_id))
            try:
                e["lines"].append(int(line_s))
            except ValueError:
                failures.append("bad LINE %r in %s" % (line_s, entry_id))
            e["pairs"].add((user, etype))
            e["dates"].append(post_s)
            if cur != "USD":
                bad_currency += 1
            expected_type = "system" if user in SYSTEM_USERS else ("manual" if user in HUMAN_USERS else None)
            if expected_type is None or etype != expected_type:
                bad_type_users.add((user, etype))
            if post_s < START_DATE.isoformat() or post_s > END_DATE.isoformat():
                out_of_range_dates.append((entry_id, post_s))

    unbalanced = [eid for eid, e in entries.items() if e["sum"] != 0]
    if unbalanced:
        failures.append("unbalanced entries (%d): e.g. %s" % (len(unbalanced), ", ".join(unbalanced[:5])))
    bad_numbering = []
    for eid, e in entries.items():
        n = len(e["lines"])
        if sorted(e["lines"]) != list(range(1, n + 1)):
            bad_numbering.append(eid)
    if bad_numbering:
        failures.append("LINE numbering broken in %d entries: e.g. %s" % (len(bad_numbering), ", ".join(bad_numbering[:5])))
    if bad_type_users:
        failures.append("ENTRY_TYPE/USER inconsistencies: %s" % sorted(bad_type_users)[:5])
    if bad_currency:
        failures.append("non-USD rows: %d" % bad_currency)
    if out_of_range_dates:
        failures.append("dates outside window (%d): e.g. %s" % (len(out_of_range_dates), out_of_range_dates[:3]))
    if abs(total_rows - requested_lines) > LINE_TOLERANCE:
        failures.append("line count %d not within +/- %d of requested %d" % (total_rows, LINE_TOLERANCE, requested_lines))

    summary = {
        "docs": len(entries),
        "lines": total_rows,
        "dmin": min((e["dates"][0] for e in entries.values()), default="n/a"),
        "dmax": max((e["dates"][-1] for e in entries.values()), default="n/a"),
    }
    return failures, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a seeded CLEAN journal-entry CSV fixture.")
    ap.add_argument("--lines", type=int, default=10000, help="target total journal lines (default: 10000)")
    ap.add_argument("--seed", type=int, default=20260823, help="RNG seed (default: 20260823)")
    ap.add_argument("--out", default="tests/fixtures/clean.csv", help="output CSV path (default: tests/fixtures/clean.csv)")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    try:
        docs, stats = generate(rng, args.lines)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    docs.sort(key=lambda r: (r["date"], r["seq"]))
    for i, r in enumerate(docs, 1):
        r["entry"] = "JE%06d" % i

    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for r in docs:
            for line_no, (acct, cents) in enumerate(r["lines"], 1):
                w.writerow([r["entry"], line_no, r["date"].isoformat(), acct, r["user"],
                            r["descr"], r["doc"], fmt_amount(cents), "USD", r["etype"]])

    print("wrote %s" % args.out)
    failures, summary = check_file(args.out, args.lines)

    print("self-check:")
    print("  balance-to-zero per ENTRY : %s" % ("OK" if not any("unbalanced" in f or "malformed" in f for f in failures) else "FAIL"))
    print("  ENTRY_TYPE/USER consistency: %s" % ("OK" if not any("ENTRY_TYPE/USER" in f for f in failures) else "FAIL"))
    print("  LINE numbering            : %s" % ("OK" if not any("LINE numbering" in f for f in failures) else "FAIL"))
    print("  currency/date/count       : %s" % ("OK" if not any("non-USD" in f or "outside window" in f or "line count" in f for f in failures) else "FAIL"))

    print("summary:")
    print("  documents   : %d" % summary["docs"])
    print("  total lines : %d (requested %d)" % (summary["lines"], args.lines))
    print("  date range  : %s .. %s" % (summary["dmin"], summary["dmax"]))
    print("  per-pattern:")
    grand = sum(v[1] for v in stats.values()) or 1
    for name in sorted(stats):
        dc, lc = stats[name]
        print("    %-16s docs=%-5d lines=%-6d %.1f%%" % (name, dc, lc, 100.0 * lc / grand))

    if failures:
        print("FAILED checks:", file=sys.stderr)
        for f in failures:
            print("  - %s" % f, file=sys.stderr)
        return 1
    print("all self-checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
