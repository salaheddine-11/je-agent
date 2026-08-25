"""Stress-test population generator — realistic bases + labeled anomaly injections.

Every generated CSV row is deterministic under a fixed seed. Anomalies are
injected with known labels so recall/precision are measurable:

  base rows      : balanced two-line entries, ordinary accounts, realistic noise
                   (legit-rare users, legit-large invoices, month-start dates),
                   so FALSE POSITIVES can actually occur and be measured.
  injections     : one document each, carrying (rule_expected, kind) metadata,
                   covering all 10 rules.

CSV columns: REF,LINE,DATE,DOCDAT,ACCT,USER,DESC,DOCREF,AMOUNT,CUR,TYPE
  DATE = posting date; DOCDAT = document date (divergence rule)

Scale target: 100k+ docs (200k+ lines). Generation is plain f-strings into a
list, joined once — handles 200k rows in seconds.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


USERS = ["K.MANSOURI", "S.ELFASI", "H.AITLA", "M.BENNANI", "Z.BERRADA"]
# legit-low-frequency users: appear only a few times, must NOT be flagged —
# this is the noise that exercises precision.
LEGIT_RARE_USERS = ["R.GHALI", "N.FAROUK", "I.TAJI", "O.KADIRI", "A.OUAZZANI"]
BASE_ACCOUNTS = ["400000", "420000", "450000", "610000", "620000"]
BANK = "51410000"
MONTH_DAYS = 28


@dataclass
class Scenario:
    name: str
    seed: int
    n_base_docs: int
    anomalies: list = field(default_factory=list)   # [(doc_id, rule_expected, kind)]
    lines: list = field(default_factory=list)
    header: str = "REF,LINE,DATE,DOCDAT,ACCT,USER,DESC,DOCREF,AMOUNT,CUR,TYPE"


def _ln(ref: str, line: int, d: str, docdat: str, acct: str, user: str,
        desc: str, docref: str, amount: float, typ: str = "manual") -> str:
    return f"{ref},{line},{d},{docdat},{acct},{user},{desc},{docref},{amount:.2f},USD,{typ}"


def _dd(d: str) -> str:
    """Default document date = posting date (benign)."""
    return d


def _date(seed_rng: random.Random, month: int, day: int | None = None) -> str:
    d = day if day is not None else seed_rng.randint(2, MONTH_DAYS - 2)
    return f"2024-{month:02d}-{d:02d}"


def _base_doc(rng: random.Random, idx: int, month: int) -> tuple[str, list[str]]:
    """One balanced 2-line doc with benign realism; returns (ref, [csv lines])."""
    ref = f"B{idx:07d}"
    acct = rng.choice(BASE_ACCOUNTS)
    # ~5% of users are legit-low-frequency (rare but honest) — precision noise
    user = rng.choices(USERS + LEGIT_RARE_USERS,
                       weights=[190, 190, 190, 190, 190, 1, 1, 1, 1, 1])[0]
    r = rng.random()
    if r < 0.03:
        amount = round(rng.uniform(180_000, 420_000), 2)   # legit big invoice
    elif r < 0.80:
        amount = round(rng.uniform(800, 42_000), 2)
    else:
        amount = round(rng.uniform(42_000, 120_000), 2)
    if rng.random() < 0.05:
        d = f"2024-{month:02d}-01"                          # month-start posting
    elif rng.random() < 0.03:
        wk = (rng.randint(2, 5) * 7) % MONTH_DAYS + 1       # approx "weekend-ish"
        d = f"2024-{month:02d}-{min(wk, MONTH_DAYS):02d}"
    else:
        d = _date(rng, month)
    desc = rng.choice(["supplier invoice", "utility fee", "service fee",
                       "rent charge", "office supplies"])
    # ~10% of entries come from SYSTEM jobs (IDOC_AUTO / WF-BATCH / SAP_JOB) —
    # realistic ERA mix; the pair-baseline rules need system entries to work on.
    if rng.random() < 0.10:
        user = rng.choice(["IDOC_AUTO", "WF-BATCH", "SAP_JOB"])
        typ = "system"
    else:
        typ = "manual"
    lines = [
        _ln(ref, 1, d, _dd(d), acct, user, desc, f"{ref}D", -amount, typ=typ),
        _ln(ref, 2, d, _dd(d), BANK, user, desc, f"{ref}D", amount, typ=typ),
    ]
    return ref, lines


def build_scenario(name: str, n_docs: int, seed: int,
                   anomaly_spec: dict | None = None) -> Scenario:
    """n_docs base docs + injected anomalies from anomaly_spec counts."""
    rng = random.Random(seed)
    sc = Scenario(name=name, seed=seed, n_base_docs=n_docs)
    all_lines: list[str] = []
    next_idx = 0

    # ---- realistic base ---------------------------------------------------
    for i in range(n_docs):
        month = rng.randint(1, 12)
        ref, ls = _base_doc(rng, next_idx, month)
        next_idx += 1
        all_lines.extend(ls)

    # ---- injections -------------------------------------------------------
    spec = anomaly_spec or {}
    counter = 10_000

    def add(anom_lines: list[str], rule: str, kind: str):
        nonlocal counter
        doc_id = f"A{counter}"
        counter += 1
        sc.anomalies.append((doc_id, rule, kind))
        all_lines.extend(anom_lines)

    for _ in range(spec.get("round_amounts", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        amt = float(rng.choice([50_000, 120_000, 250_000, 500_000]))
        add([_ln(f"A{counter}", 1, d, _dd(d), "610000", u, "consulting",
                 f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, u, "consulting",
                 f"A{counter}D", amt)],
            "round_amounts", "round")

    for _ in range(spec.get("entry_splitting", 0)):
        # rule band: amounts in [split_just_below_ratio*split_threshold,
        # split_threshold) i.e. just below split_threshold (default 10,000).
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        parts = rng.choice([3, 4])
        each = round(rng.uniform(9_050, 9_950), 2)
        parent = f"A{counter}"
        counter += 1
        refs = []
        for p in range(parts):
            refp = f"{parent}P{p + 1}"
            refs.append(refp)
            all_lines.append(_ln(refp, 1, d, _dd(d), "620000", u,
                                 f"split invoice {p + 1}/{parts}", parent, -each))
            all_lines.append(_ln(refp, 2, d, _dd(d), BANK, u,
                                 f"split invoice {p + 1}/{parts}", parent, each))
        # the rule flags the PART refs; label those (parent ref never flagged)
        sc.anomalies.extend((rp, "entry_splitting", "split_part") for rp in refs)

    for _ in range(spec.get("period_end", 0)):
        # observation window is AFTER period end (2024-12-31 + post_close_days)
        d = f"2025-01-{rng.randint(1, 5):02d}"
        u = rng.choice(USERS)
        amt = round(rng.uniform(30_000, 90_000), 2)
        add([_ln(f"A{counter}", 1, d, _dd(d), "450000", u, "year-end accrual",
                 f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, u, "year-end accrual",
                 f"A{counter}D", amt)],
            "period_end", "post_close")

    for _ in range(spec.get("unusual_pairs", 0)):
        # unique asset account per injection -> pair never in the system baseline
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        amt = round(rng.uniform(60_000, 300_000), 2)
        asset = f"23{rng.randint(1, 99):02d}{rng.randint(1, 9):02d}00"
        add([_ln(f"A{counter}", 1, d, _dd(d), asset, u,
                 "asset purchase via expense flow", f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, u,
                 "asset purchase via expense flow", f"A{counter}D", amt)],
            "unusual_pairs", "pair")

    # each injection uses a fresh distinct username, so their manual-line count
    # stays at exactly 2 (<= rare threshold 5) no matter how many run.
    for i in range(spec.get("unusual_users", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = f"RARE.{rng.choice(USERS)[0]}.{i:02d}"
        amt = round(rng.uniform(20_000, 70_000), 2)
        add([_ln(f"A{counter}", 1, d, _dd(d), "400000", u,
                 "rare-user manual post", f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, u,
                 "rare-user manual post", f"A{counter}D", amt)],
            "unusual_users", "rare_user")

    for _ in range(spec.get("balance_check", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        amt = round(rng.uniform(15_000, 55_000), 2)
        off = round(amt * 0.02, 2)                        # deliberately unbalanced
        add([_ln(f"A{counter}", 1, d, _dd(d), "610000", u, "broken entry",
                 f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, u, "broken entry",
                 f"A{counter}D", off)],
            "balance_check", "unbalanced")

    for _ in range(spec.get("date_divergence", 0)):
        # document date far from posting date (backdating-style signal)
        pd = f"2024-{rng.randint(1, 12):02d}-{rng.randint(2, 25):02d}"
        mm = int(pd[5:7]); base_day = int(pd[8:10])
        dd = f"2024-{mm:02d}-{min(base_day + rng.randint(12, 22), 28):02d}"
        u = rng.choice(USERS)
        amt = round(rng.uniform(5_000, 40_000), 2)
        add([_ln(f"A{counter}", 1, pd, dd, "400000", u, "mismatched dates",
                 f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, pd, dd, BANK, u, "mismatched dates",
                 f"A{counter}D", amt)],
            "date_divergence", "docdate_mismatch")

    for _ in range(spec.get("high_risk_system_pairs", 0)):
        # system-type entry on an unusual account pair (rare combo) — unique
        # asset so it differs from unusual_pairs injections and stays unusual.
        m = rng.randint(1, 12); d = _date(rng, m)
        amt = round(rng.uniform(30_000, 200_000), 2)
        asset = f"23{rng.randint(1, 99):02d}{rng.randint(1, 9):02d}00"
        add([_ln(f"A{counter}", 1, d, _dd(d), asset, "SAP_JOB",
                 "auto asset via system", f"A{counter}D", -amt, typ="system"),
             _ln(f"A{counter}", 2, d, _dd(d), BANK, "SAP_JOB",
                 "auto asset via system", f"A{counter}D", amt, typ="system")],
            "high_risk_system_pairs", "sys_pair")

    for _ in range(spec.get("reversals", 0)):
        # original in-period (Dec 2024), reversal AFTER period end (Jan 2025)
        u = rng.choice(USERS)
        amt = round(rng.uniform(25_000, 95_000), 2)
        d1 = f"2024-12-{rng.randint(10, 28):02d}"
        d2 = f"2025-01-{rng.randint(2, 8):02d}"
        add([_ln(f"A{counter}", 1, d1, _dd(d1), "620000", u, "erroneous charge",
                 f"A{counter}D", -amt),
             _ln(f"A{counter}", 2, d1, _dd(d1), BANK, u, "erroneous charge",
                 f"A{counter}D", amt)],
            "reversals", "original")
        add([_ln(f"A{counter}", 3, d2, _dd(d2), "620000", u, "reversal",
                 f"A{counter}D", amt),
             _ln(f"A{counter}", 4, d2, _dd(d2), BANK, u, "reversal",
                 f"A{counter}D", -amt)],
            "reversals", "reversal_side")

    sc.lines = [sc.header] + all_lines
    return sc


def write_csv(sc: Scenario, path) -> None:
    path.write_text("\n".join(sc.lines), encoding="utf-8")
