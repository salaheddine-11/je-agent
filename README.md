# JE Agent

### Journal-Entry Testing AI Agent — ISA 240 / AS 2401

JE Agent is an **audit assistant for journal entries**. It reads an export of
journal entries, flags the ones that deserve a closer look, and produces a
**professional audit report** (PDF + Excel workpaper) — with AI-assisted
reasoning on top of hard, deterministic rules, and the auditor's own judgment
always in charge.

> **Why it exists.** ISA 240 / AS 2401 requires auditors to consider the risk of
> fraud in journal entries. Reviewing 100,000+ entries by hand is slow and
> error-prone. JE Agent does the heavy lifting: it flags *everything suspicious*,
> ranks what matters, and prints a report you can take to the client.

---

## What you get

| Output | What it is |
|---|---|
| **report.pdf** | A4 audit report: summary, findings (5C structure), rule matrix, Benford chart, limitations |
| **report.html** | The same report as a webpage |
| **workpaper.xlsx** | The full review workpaper — every flag, every decision, traceable |
| **flagged_entries.xlsx** | The review queue — what to look at, in priority order |

**The three layers** (and why this is more than another spreadsheet):

1. **Deterministic rules** — 10 audit rules (round amounts, entries near period
   end, split invoices, unbalanced entries, unusual users, reversals, date
   mismatches, unusual account pairs, system entries by high-risk users,
   manual entries). No AI opinion — pure logic, reproducible every time.
2. **AI triage** — an LLM reads the flagged entries and ranks them, explaining
   *why* each one matters. The report labels AI reasoning as AI reasoning.
3. **Human review** — you (the auditor) decide each entry: *inspect* or
   *accept*. Your decisions are **hash-chained** — nobody can silently change
   them later — and the agent **refuses to finalize** until every entry has
   your decision or an accepted limitation.

**Integrity by construction:** deterministic (same file → same flags), no
hallucinated sources (AI must cite facts that exist), tamper-evident decisions,
no silent output (gates block incomplete runs), PII scrubbed and zero-retention
LLM mode by default.

---

## Quickstart (5 minutes, no technical knowledge)

### 1 — Install Python (once)

- **Windows:** download from [python.org](https://www.python.org/downloads/) — tick **"Add Python to PATH"** during install.
- **macOS/Linux:** Python 3.12+ is usually already there; otherwise use your package manager.

Then install **uv** (the project's single tool):

```bash
# Windows (in any terminal):
pip install uv

# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2 — Get the project + its dependencies

```bash
git clone https://github.com/salaheddine-11/je-agent.git
cd je-agent
uv sync
```

(That last command installs everything automatically — no pip, no venv steps.)

### 3 — Start JE Agent

```bash
uv run jeagent serve
```

Then open **http://localhost:8300** in your browser. Login key: **`jeagent`**
(change it with `uv run jeagent serve --key your-secret-key`).

That's it. The console guides you through the rest.

---

## Using the console

1. **New engagement** → pick your journal-entry CSV → the agent **auto-detects**
   the columns for you (or you adjust the mapping in the form).
2. Pick **English 🇬🇧 or Français 🇫🇷** for the interface *and* the report.
3. Choose **Human review** (you decide each entry) or **AI review** (the agent
   decides from its triage — for demo/practice, not a substitute for a human's
   substantive testing).
4. **Start the run** — the agent ingests, applies all 10 rules, and flags the
   review universe.
5. **Review tab** → click any entry to see its journal lines and the rules it
   triggered → decide **inspect** or **accept** (with a reason).
6. **Finalize** → your report + workpaper are generated automatically. If
   anything is missing (undecided entries, unaccepted limitations), it tells
   you exactly what.

> **Making a French report:** set the report language to FR in the form.
> **Deleting an old engagement:** the trash icon on the Engagements list.

---

## What it takes to run

| Requirement | Details |
|---|---|
| **OS** | Windows, macOS or Linux |
| **Python** | 3.12+ |
| **Internet** | Only for the AI steps (triage, narrative) — uses Gemini's free tier by default; the deterministic pipeline runs offline |
| **Data** | A CSV export of journal entries (column names are auto-detected) |

### API key for the AI features (optional)

The AI layers need a model key (Gemini's free tier is fine, ~20 requests/min):

```
uv run jeagent serve --key YOUR_SECRET_KEY     # console login key
Gemini API key → JEAGENT_API_KEY env var, or set base_url/model in the UI
```

---

## What it is *not*

- ❌ Not a fraud detector — it **flags risks**; it doesn't conclude fraud.
- ❌ Not a substitute for human substantive testing or vouching.
- ❌ Not a guarantee you'll catch everything — suspicious ≠ fraud, and some
  real anomalies are indistinguishable from clean activity at scale (see the
  stress-test numbers in the project report).
- Every report states its limitations (§11). The agent **blocks finalization**
  if you haven't acknowledged them.

---

## For developers

### Commands

```bash
uv run jeagent serve                    # console (single command)
uv run jeagent start -c config.yaml -e extract.csv   # CLI pipeline
uv run jeagent status <RUN_ID>          # run status
uv run jeagent finalize <RUN_ID>        # auto-produce deliverables
uv run jeagent test-connection          # check your LLM endpoint
uv run pytest                           # 169+ tests
```

### Layout

```
src/je_agent/     core: rules, ingest, triage, review, narrative, report, API
web/              React console (served by the API on one port)
scripts/          stress-test harness, pilots
tests/            169+ tests incl. adversarial-injection suite
DESIGN.md         consolidated design v1.6 (amendments logged)
PROJECT_REPORT.md idea, design, tests & evaluation (with real numbers)
```

### Stress-test evidence (summary)

Labeled synthetic populations from 2k to 200k lines:

- Detection recall **99–100%** at every scale (10 rules, all injected classes caught)
- Precision falls as population grows (74% → 6%): benign patterns can look like
  anomalies at scale — **the human auditor is where precision is made**
- LLM triage caught **100%** of injected anomalies, with 41% inspect precision
- Measured tuning: `period_end_window_days=1` + `unusual_account_share=0.02`
  double precision at zero recall loss (medium scenario)

Full details in `PROJECT_REPORT.md`.

---

## Version

**v1.0.0** — released. Design document v1.6 is the single source of truth;
deviations are logged as numbered amendments, never silent.

Built with **Hermes Agent** (Nous Research).
