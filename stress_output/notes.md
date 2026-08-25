# JE Agent — Stress-Test Results (labeled anomalies)

Generated 2026-08-25 17:11 · total run time 8.9s · deterministic rules (LLM triage leg separate).

## Methodology (v2)

Synthetic journal populations with **known injected anomalies**, one labeled document per case, covering all 10 rules. Base populations are **realistic, not sterile**: ~90% manual + ~10% system-posted entries (IDOC_AUTO / WF-BATCH / SAP_JOB), legit-rare users (~5%), legitimately large invoices, month-start postings — so false positives CAN occur and are measured.

**Scoring** — for each rule: `tp` = injected anomalies flagged, `fn` = injected missed, `fp` = flags on clean base docs (the noise). Recall = tp/(tp+fn); precision = tp/(tp+fp); F1 = harmonic mean. Out-of-scope injections (below performance materiality, excluded by design) are excluded from universe recall.

**Rules injected:** round_amounts, entry_splitting, period_end, unusual_pairs, unusual_users, balance_check, reversals, date_divergence, high_risk_system_pairs, manual_entries (implicit — everything is a journal entry).

## Aggregate

| Scenario | Lines | Injections | Recall | Precision | F1 | Universe recall (PM-scoped) |
|---|---|---|---|---|---|---|
| medium | 20,210 | 105 | 100.00% | 42.34% | 59.49% | 100.00% (7/7 above-PM) |
## medium (20,210 lines)
- round_amounts: recall 100.00%, precision 66.67%, F1 80.00% (12/12 caught, 6 false positives)
- entry_splitting: recall 100.00%, precision 20.35%, F1 33.82% (35/35 caught, 137 false positives)
- period_end: recall 100.00%, precision 100.00%, F1 100.00% (8/8 caught, 0 false positives)
- unusual_pairs: recall 100.00%, precision 100.00%, F1 100.00% (10/10 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 100.00%, F1 100.00% (8/8 caught, 0 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (6/6 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (12/12 caught, 0 false positives)
- date_divergence: recall 100.00%, precision 100.00%, F1 100.00% (8/8 caught, 0 false positives)
- high_risk_system_pairs: recall 100.00%, precision 100.00%, F1 100.00% (6/6 caught, 0 false positives)
- universe: 253 selected of 253 refs; 7/7 above-PM injected anomalies in universe (recall 100.00%)
