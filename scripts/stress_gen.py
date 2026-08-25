"""Stress-test population generator — clean bases + labeled anomaly injections.

Every generated CSV row is deterministic under a fixed seed. Anomalies are
injected with known labels so recall/precision are measurable:

  base rows      : balanced two-line entries, ordinary accounts, mid-month dates,
                   recurring users, non-round amounts.
  injections     : one document each, carrying (rule_expected, kind) metadata.

Scale target: 100k+ lines. Generation is vectorized-free (plain f-strings into a
list, joined once) which handles 100k rows in a couple of seconds.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


USERS = ["K.MANSOURI", "S.ELFASI", "H.AITLA", "M.BENNANI", "Z.BERRADA"]
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
    header: str = ("REF,LINE,DATE,ACCT,USER,DESC,DOCREF,AMOUNT,CUR,TYPE")


def _date(seed_rng: random.Random, month: int, day: int | None = None) -> str:
    d = day if day is not None else seed_rng.randint(2, MONTH_DAYS - 2)
    return f"2024-{month:02d}-{d:02d}"


def _base_doc(rng: random.Random, idx: int, month: int) -> tuple[str, list[str]]:
    """One balanced 2-line doc; returns (ref, [csv lines])."""
    ref = f"B{idx:07d}"
    acct = rng.choice(BASE_ACCOUNTS)
    user = rng.choice(USERS)
    amount = round(rng.uniform(800, 42_000), 2)          # never round-thousand
    d = _date(rng, month)
    desc = rng.choice(["supplier invoice", "utility fee", "service fee",
                       "rent charge", "office supplies"])
    lines = [
        f"{ref},1,{d},{acct},{user},{desc},{ref}D,-{amount:.2f},USD,manual",
        f"{ref},2,{d},{BANK},{user},{desc},{ref}D,{amount:.2f},USD,manual",
    ]
    return ref, lines


def build_scenario(name: str, n_docs: int, seed: int,
                   anomaly_spec: dict | None = None) -> Scenario:
    """n_docs base docs + injected anomalies from anomaly_spec counts."""
    rng = random.Random(seed)
    sc = Scenario(name=name, seed=seed, n_base_docs=n_docs)
    all_lines: list[str] = []
    next_idx = 0

    # ---- clean base -------------------------------------------------------
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
        add([f"A{counter},1,{d},610000,{u},consulting,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d},51410000,{u},consulting,{f'A{counter}D'},{amt:.2f},USD,manual"],
            "round_amounts", "round")

    for _ in range(spec.get("entry_splitting", 0)):
        # rule band: amounts in [split_just_below_ratio*split_threshold, split_threshold)
        # i.e. just below split_threshold (default 10,000) — NOT below materiality.
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        parts = rng.choice([3, 4])
        each = round(rng.uniform(9_050, 9_950), 2)       # in [9,000, 10,000)
        parent = f"A{counter}"
        counter += 1
        refs = []
        for p in range(parts):
            refp = f"{parent}P{p + 1}"
            refs.append(refp)
            all_lines.append(f"{refp},1,{d},620000,{u},split invoice {p + 1}/{parts},{parent},-{each:.2f},USD,manual")
            all_lines.append(f"{refp},2,{d},51410000,{u},split invoice {p + 1}/{parts},{parent},{each:.2f},USD,manual")
        # the rule flags the PART refs; label those (parent ref never flagged)
        sc.anomalies.extend((rp, "entry_splitting", "split_part") for rp in refs)

    for _ in range(spec.get("period_end", 0)):
        # observation window is AFTER period end (2024-12-31 + post_close_days)
        d = f"2025-01-{rng.randint(1, 5):02d}"
        u = rng.choice(USERS)
        amt = round(rng.uniform(30_000, 90_000), 2)
        add([f"A{counter},1,{d},450000,{u},year-end accrual,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d},51410000,{u},year-end accrual,{f'A{counter}D'},{amt:.2f},USD,manual"],
            "period_end", "post_close")

    for _ in range(spec.get("unusual_pairs", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        amt = round(rng.uniform(60_000, 300_000), 2)
        add([f"A{counter},1,{d},23320000,{u},asset purchase via expense flow,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d},51410000,{u},asset purchase via expense flow,{f'A{counter}D'},{amt:.2f},USD,manual"],
            "unusual_pairs", "pair")

    # each injection uses a fresh distinct username, so their manual-line count
    # stays at exactly 2 (<= rare threshold 5) no matter how many run.
    for i in range(spec.get("unusual_users", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = f"RARE.{rng.choice(USERS)[0]}.{i:02d}"
        amt = round(rng.uniform(20_000, 70_000), 2)
        add([f"A{counter},1,{d},400000,{u},rare-user manual post,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d},51410000,{u},rare-user manual post,{f'A{counter}D'},{amt:.2f},USD,manual"],
            "unusual_users", "rare_user")

    for _ in range(spec.get("balance_check", 0)):
        m = rng.randint(1, 12); d = _date(rng, m)
        u = rng.choice(USERS)
        amt = round(rng.uniform(15_000, 55_000), 2)
        off = round(amt * 0.02, 2)                        # deliberately unbalanced
        add([f"A{counter},1,{d},610000,{u},broken entry,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d},51410000,{u},broken entry,{f'A{counter}D'},{off:.2f},USD,manual"],
            "balance_check", "unbalanced")

    for _ in range(spec.get("reversals", 0)):
        # original in-period (Dec 2024), reversal AFTER period end (Jan 2025)
        u = rng.choice(USERS)
        amt = round(rng.uniform(25_000, 95_000), 2)
        d1 = f"2024-12-{rng.randint(10, 28):02d}"
        d2 = f"2025-01-{rng.randint(2, 8):02d}"
        add([f"A{counter},1,{d1},620000,{u},erroneous charge,{f'A{counter}D'},-{amt:.2f},USD,manual",
             f"A{counter},2,{d1},51410000,{u},erroneous charge,{f'A{counter}D'},{amt:.2f},USD,manual"],
            "reversals", "original")
        add([f"A{counter},3,{d2},620000,{u},reversal,{f'A{counter}D'},{amt:.2f},USD,manual",
             f"A{counter},4,{d2},51410000,{u},reversal,{f'A{counter}D'},{-amt:.2f},USD,manual"],
            "reversals", "reversal_side")

    sc.lines = [sc.header] + all_lines
    return sc


def write_csv(sc: Scenario, path) -> None:
    path.write_text("\n".join(sc.lines), encoding="utf-8")
