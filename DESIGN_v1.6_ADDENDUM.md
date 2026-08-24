# JE Agent — Design Addendum v1.6

Resolves review findings F1–F7 (2026-08-23 orchestrator review of DESIGN.md v1.5).
Style follows the established amendment log. No prior resolutions changed; this
document only adds specifications where v1.5 was silent.

---

## Amendment Log — v1.6

| ID | Finding | Resolution | Where |
|----|---------|------------|-------|
| Z1 | `reversals` requires post-period-end data; extract contract never guarantees it | Extract coverage declaration + `dq_no_post_close_coverage` warning + limitation text | §3.2, §5.9, §11 |
| Z2 | `unusual_pairs` baseline depends on "documents flagged on a prior pass" — execution order unspecified, breaking the determinism claim | Canonical rule-execution order fixed in the registry; executor enforces it regardless of RiskPlan ordering; order recorded in `tool_calls` | §5.4, §5.6 |
| Z3 | `is_manual` derivation heuristic undefined | Two-tier specification: explicit source column first, then username-pattern heuristic; both fixture-covered | §5.6, §6.2, §9.2 |
| Z4 | Nightly 5M-line × 4-shape benchmark cannot run on the development machine (12 GB RAM) | Split gates: full matrix runs remotely (CI) nightly and stays release-blocking; local PR gate is a reduced smoke benchmark (500k lines, ≤ 90 s, ≤ 2 GB RSS) | §9.4 |
| Z5 | Windows specifics unstated (PID liveness, DuckDB file locks, heartbeats during long statements) | Portability requirements: psutil-based liveness, read-only open mode tested on Windows, watchdog heartbeat thread (60 s cadence), `windows-latest` CI leg from Phase 1 | §4.8, §9.4 |
| Z6 | Hash-chain genesis undefined | Chains are per-table per-run; genesis `prev_hash = "0" * 64`; `row_hash = SHA-256(prev_hash ‖ 0x00 ‖ canonical_json(row minus hash))`; `verify_chain()` utility ships Phase 1 | §7.2, §7.3 |
| Z7 | `entry_splitting` threshold silently coupled to `round_number_min_amount` | Independent `rule_params.split_threshold` (initial value 10000, mirroring the old coupling); decoupled thereafter | §3.2, §5.6 |

---

## Z1 — Extract coverage & the `reversals` rule

**Problem.** `flag_reversals` matches near-negations occurring *after* period end
(`reversal_match_days`). If the client extract ends exactly at period end, the rule
silently tests nothing while appearing to have passed — a false comfort result.

**Specification.**

1. New optional config field under `source:`:

   ```yaml
   source:
     extract_through_date: 2026-07-15   # declared last posting date covered by the extract
   ```

2. At INGEST, the profiler computes `observed_max_posting_date` from the canonical
   table. Three-way comparison, emitted as data-quality warnings:

   - `dq_extract_shortfall_declared` (**critical**) — observed max posting date is
     earlier than the declared `extract_through_date`. The extract does not contain
     what the engagement letter said it would. Non-dismissible.
   - `dq_no_post_close_coverage` (**warning**) — observed max posting date (or the
     declared date, whichever is smaller) is earlier than
     `period_end + rule_params.reversal_match_days`. `reversals` still executes, but
     its `ToolResult.notes` state the truncated observation window.
   - No warning when coverage suffices.

3. Workpaper impact (Scope & Limitations): whenever `dq_no_post_close_coverage`
   is active **or** was acknowledged, the limitations section states: *"The reversal
   screen observed N days past period end (window requested: M days)."*

**Rationale.** Mirrors Y5's philosophy: acknowledgment documents a finding, it
cannot erase it. The critical class catches the worse failure (declared coverage
not delivered); the warning class handles the ordinary "we pulled the extract at
period end" case honestly.

---

## Z2 — Canonical rule-execution order

**Problem.** `unusual_pairs` excludes documents flagged by any *prior* rule (C3).
Without a fixed sequence, two valid executions could produce different baselines
and different flags — violating the byte-identical double-run guarantee (§4.5).

**Specification.**

The registry defines one canonical order; the EXECUTE stage sorts all selected
rules into it regardless of how the RiskPlan listed them:

```
1. manual_entries          (single-pass, defines is_manual consumers)
2. period_end              (depends on 1)
3. round_amounts           (single-pass)
4. date_divergence         (single-pass)
5. entry_splitting         (single-pass)
6. balance_check           (single-pass)
7. unusual_users           (depends on 1)
8. unusual_pairs           (baseline excludes docs flagged by 1–7)
9. reversals               (post-period screen; excluded from 8's baseline input)
10. high_risk_system_pairs (informational, never gating, always last)
```

Rules:

- `unusual_pairs` consumes exactly the flag tables of steps 1–7 (the rules that
  precede it in canonical order). Later-running rules (`reversals`) intentionally do
  **not** feed the baseline exclusion — their hits occur outside the baseline's
  in-period definition.
- The executed order is recorded in `tool_calls.seq` and asserted in the
  reproducibility suite: reordering a RiskPlan's selection list must not change
  any `flags_*` table.
- Statistical tools (`run_benford`, `run_outlier_detection`,
  `sample_representative`) execute after step 10; they consume the canonical table
  only and never affect flags.

**Rationale.** Makes the C3 exclusion deterministic and auditable; costs nothing;
removes an ambiguity the golden-fixture suite would otherwise paper over.

---

## Z3 — `is_manual` derivation heuristic (two tiers)

**Problem.** §6.2 says `is_manual` comes "from source entry_type if present, else
derived" — the derived branch is unspecified, yet it drives the most important rule.

**Specification.**

Tier 1 — **explicit source column.** When `column_map.entry_type` maps a source
column, values are matched case-insensitively against `rule_params.manual_entry_types`
(default `["manual", "man", "m"]`). Match → `TRUE`; anything else → `FALSE`;
blank/null → `FALSE`. `entry_type_source = 'source'`.

Tier 2 — **derived heuristic** (no entry-type column mapped). A line is manual iff:

> `username` is non-blank **and** does not match any pattern in
> `rule_params.system_user_patterns`

Default patterns (case-insensitive wildcards, `*` = any run of characters):

```yaml
system_user_patterns:
  - "SAP*"
  - "WF-BATCH"
  - "BATCH*"
  - "SYSTEM"
  - "AUTO*"
  - "JOB*"
  - "INTERFACE*"
  - "*_RFC"        # RFC/system communication users
```

Blank or null `username` → `FALSE` (not provably human) and counts toward the
existing missing-field DQ rate. `entry_type_source = 'derived'`.

Both parameter lists live in the frozen engagement config — changing them is part
of reproducibility identity like every other `rule_param`.

**Fixtures.** The golden suite must cover, per tier: positive manual, negative
system-pattern user, blank username, case-insensitivity, and one
pattern-boundary case (`SAPUSER` vs `ASAPUSER` must not match `"SAP*"`).

**Rationale.** Deliberately conservative (defaults to *not* manual when unsure):
under-flagging manual entries is worse than over-flagging obvious system noise,
and the heuristic's provenance is always visible via `entry_type_source`.

---

## Z4 — Split performance gates (hardware-honest)

**Problem.** The nightly benchmark matrix (§9.4/W9: ~5M lines × 4 shapes, ≤ 10 min,
≤ 8 GB RSS) cannot execute on the current dev machine (i3 2C/4T, 12 GB RAM) without
starving everything else.

**Specification.**

- **PR gate (local):** `benchmark --scale smoke` — 500k lines, one representative
  shape (mixed), budget ≤ 90 s wall / ≤ 2 GB RSS. Blocking locally; catches
  complexity regressions (the accidental O(n²)).
- **Nightly/release gate (CI):** full W9 matrix at ~5M lines × 4 shapes with
  original budgets (≤ 10 min / ≤ 8 GB RSS per shape), plus the crash-recovery kill
  matrix (X4/Y7). Runs on a CI runner with ≥ 16 GB RAM; release-blocking there.
  Locally the full matrix is skipped with an explicit marker (`@pytest.mark.fullscale`)
  so the skip is visible, never silent.

Until the repository gains a CI remote, the release gate is recorded as
**pending-remote** in the build log; Phase 1 exit criteria require the smoke gate
plus green golden/reproducibility suites, and the full matrix becomes blocking the
day CI exists.

---

## Z5 — Windows portability requirements

**Problem.** Development runs on Windows; several specified mechanisms have
platform-specific failure modes that must be designed-in, not discovered later.

**Specification.**

1. **PID liveness** (X4): implemented exclusively via `psutil` —
   `pid_exists(pid)` plus a `create_time` cross-check against the lock's issuance
   timestamp (defeats PID reuse). No POSIX signal tricks.
2. **Heartbeat:** a daemon thread writes the lock's heartbeat every 60 s
   (threshold 300 s ⇒ five missed beats before staleness), so long single SQL
   statements can't orphan a healthy run. Heartbeat write failures are logged, not fatal.
3. **DuckDB access modes:** non-orchestrator readers must open
   `duckdb.connect(path, read_only=True)`; a test asserts a second read-only
   connection works while the writer holds the database, and that a second
   read-write attempt fails cleanly, **on Windows** specifically.
4. **Locks:** `run.lock` / `run.recovery.lock` creation uses exclusive-create
   (`os.open(..., O_CREAT | O_EXCL)`) — atomic on NTFS; recovery lock contention
   test (Y7) must pass on Windows.
5. **Paths:** `pathlib.Path` everywhere; no hardcoded separators; the run folder
   layout (§6.1) is platform-neutral.
6. **CI topology:** from Phase 1, CI runs the unit/golden suites on both
   `ubuntu-latest` and `windows-latest`; performance legs per Z4.

---

## Z6 — Hash-chain genesis and verification

**Problem.** W7/X3 specify chained `row_hash` values but never define the first row
or how the chain is verified.

**Specification.**

- Chains are **per-table, per-run** (`review_decisions`, `dq_acknowledgments`,
  `injection_dispositions` each chain independently within one `run_id`).
- Genesis row: `row_hash = SHA-256("0" * 64 ‖ 0x00 ‖ canonical_json(payload))`
  where payload is the row without `row_hash`.
- Subsequent rows substitute the previous row's `row_hash` for the zero prefix.
- `canonical_json` = UTF-8, keys sorted, no insignificant whitespace — serialized
  by one shared utility so producers and verifiers cannot diverge.
- `verify_chain(table, run_id) -> ChainReport` ships in Phase 1 (used by the QC
  report and the workpaper AI Governance sheet: "decision log integrity: verified").

---

## Z7 — `entry_splitting` threshold decoupling

**Problem.** The split-detection trigger defaulted to `round_number_min_amount` —
a hidden coupling between two rules' parameters.

**Specification.** New independent parameter:

```yaml
rule_params:
  split_threshold: 10000    # entries below this count as "just below threshold"
```

Initial value mirrors the former effective behavior; the parameters are now
independent. Golden fixtures for `entry_splitting` set both explicitly so a future
change to either cannot silently alter split detection.

---

## Effect on Phase 1 scope

All seven resolutions land in Phase 1 (they touch schema, config, ingest, rules,
locks, and suites — all Phase 1 surfaces). Net additions to §10.1:

- `extract_through_date` handling + two DQ classes (Z1)
- Canonical-order enforcement + reorder-invariance test (Z2)
- Derivation heuristic + fixtures (Z3)
- Smoke benchmark target + `fullscale` markers (Z4)
- psutil liveness, heartbeat thread, Windows dual-access test (Z5)
- `canonical_json` / `verify_chain()` utilities (Z6 — store schema lands Phase 2,
  utilities Phase 1)
- `split_threshold` parameter (Z7)

No changes to phases 2–4 scope.
