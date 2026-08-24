# JE Agent — Journal Entry Testing AI Agent

**v1.0** · ISA 240 / AS 2401 journal-entry testing, executed as a human-supervised
AI pipeline: deterministic risk rules → LLM triage → hash-chained auditor review →
gated finalization → client-ready audit report (PDF) + workpaper.

> **Scope & use.** JE Agent is a risk-flagging, prioritization, documentation and
> review-workflow system. It is not a substitute for substantive testing or
> vouching, not a fraud-detection guarantee. Every report states §11 limitations.

---

## What it does

```
CSV extract ─► INGEST ─► RISK_PLAN ─► EXECUTE (10 rules) ─► CROSS_REF rank
                                                            │
              Gemini/Claude/local-LLM TRIAGE ◄─ packs ≤20 ◄─┘ (W1 universe cap)
                    │
              REVIEW — human decisions, hash-chained, supersede-never-update
                    │
              NARRATE — findings-voice workpaper prose with [fact:key] citations
                    │
              GATES 1–4 ─✔─► report.html + report.pdf + flagged_entries.xlsx + workpaper.xlsx
```

**Ten rules in canonical order:** manual entries · period-end proximity · round
amounts · date divergence · entry splitting · balance check · unusual users ·
unusual pairs · reversals · high-risk system pairs (informational).

**Guarantees by construction**

| Guarantee | Mechanism |
|---|---|
| Recall-first flagging | every rule hit enters ranking; golden fixtures gate CI |
| Determinism | frozen-extract SHA-256; double-run byte equality tested |
| LLM containment | `sanitize_for_llm` boundary, schema validation, one repair retry |
| No hallucinated references | `[fact:key]` citations must resolve (gate 3) |
| Tamper-evident judgments | per-table hash chains, verified at finalize |
| Nothing finalizes silently | gates block on missing reviews/procedures/citations/unaccepted limitations |

## Quickstart

```bash
# Python 3.12 via uv (pip not required)
uv sync

# 1) test your model endpoint (any OpenAI-compatible URL: Gemini, Ollama, vLLM, Azure…)
uv run jeagent test-connection \
    --base-url "https://generativelanguage.googleapis.com/v1beta/openai" \
    --model gemini-3.5-flash-lite --api-key "$GEMINI_API_KEY"

# 2) run the full pipeline (see sap_pilot_config.yaml for the config shape)
uv run jeagent start --config my_engagement.yaml --extract extract.csv

# 3) record decisions (UI recommended), then finalize:
uv run streamlit run src/je_agent/ui.py        # Review tab → decide → DQ acks
uv run jeagent finalize <RUN_ID>
#   → runs/<RUN_ID>/artifacts/{report.pdf, report.html, flagged_entries.xlsx, workpaper.xlsx}
```

CLI: `start · status · recover · export · finalize · test-connection`.

## The deliverable

Every finalized run produces an A4 PDF report: dark cover with engagement summary
and headline numbers, BLUF executive assessment, risk-rated **5C findings**
(criteria/condition/cause/consequence/corrective action), rule matrix with
drill-down detail, **Benford first-digit chart with 95% confidence whiskers**
(Nigrini MAD verdict, informational-only per amendment C2), currency-stratified
universe documentation, LLM triage reasoning, the authoritative auditor-review
table, cited narrative, and the governance appendix (§11 limitations, DQ
acknowledgments, chain-integrity verdict).

Design system: ink/slate palette, Okabe-Ito colorblind-safe chart colors,
semantic chips only. Content is computed per run — same template, different true story.

## Configuration sketch

```yaml
run_id: ENGAGEMENT_2026Q2
period_end: '2026-06-30'
materiality: {overall: 250000, performance: 175000, currency: USD}
source:
  system: sap                # column names mapped to canonical fields
  amount_column: DMBTR
  currency_column: WAERS
  column_map: {posting_date: BUDAT, account: HKONT, username: UNAME,
               source_doc: BELNR, entry_ref: BELNR, document_date: BLDAT}
  extract_through_date: '2026-07-10'
risk_context: {high_risk_users: [JSMITH], fraud_risk_factors: [year-end adjustments]}
review: {max_universe_size: 200, overflow_policy: stratify, pack_size: 20}
llm_privacy: {mode: zero_retention, pii_scrubbing: true}
representative_sample: {enabled: true, size: 25, strata: [month]}
```

## Status

- **Phase 1–3 complete** (per `DESIGN.md` v1.6): deterministic core, agent layer,
  Streamlit UI. Phase 4 (REST/React/SSO) intentionally deferred.
- **169 tests green** (`uv run pytest`), including adversarial-injection suite,
  protocol conformance for both LLM wire formats, reproducibility, and a full
  INGEST→gates E2E.
- Proven on a real 66k-line SAP extract end-to-end (deterministic + Gemini triage +
  human review + narration + finalize).

## Repository layout

```
src/je_agent/
  ingest.py rules/ crossref.py universe.py triage.py review.py
  narrate.py document.py stats.py workpaper.py report.py   # report = PDF/html deliverable
  llm/{provider,sanitize,diagnostics}.py orchestrator.py cli.py ui.py
tests/            # 169 tests incl. §9.5 adversarial corpus (opencode-generated)
scripts/          # run_full_pilot.py, run_real_triage_smoke.py, record_review.py
DESIGN.md         # v1.6 consolidated design (amendments A–Z logged in §0)
```

## License / provenance

Built with Hermes Agent (Nous Research). Design document v1.6 is the single
source of truth; deviations are logged as numbered amendments, never silent.
