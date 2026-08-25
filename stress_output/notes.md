# JE Agent — Stress-Test Results (labeled anomalies)

Generated 2026-08-25 17:03 · total run time 3.0s · deterministic rules (LLM triage leg separate).

## Methodology (v2)

Synthetic journal populations with **known injected anomalies**, one labeled document per case, covering all 10 rules. Base populations are **realistic, not sterile**: ~90% manual + ~10% system-posted entries (IDOC_AUTO / WF-BATCH / SAP_JOB), legit-rare users (~5%), legitimately large invoices, month-start postings — so false positives CAN occur and are measured.

**Scoring** — for each rule: `tp` = injected anomalies flagged, `fn` = injected missed, `fp` = flags on clean base docs (the noise). Recall = tp/(tp+fn); precision = tp/(tp+fp); F1 = harmonic mean. Out-of-scope injections (below performance materiality, excluded by design) are excluded from universe recall.

**Rules injected:** round_amounts, entry_splitting, period_end, unusual_pairs, unusual_users, balance_check, reversals, date_divergence, high_risk_system_pairs, manual_entries (implicit — everything is a journal entry).

## Aggregate

| Scenario | Lines | Injections | Recall | Precision | F1 | Universe recall (PM-scoped) |
|---|---|---|---|---|---|---|
| small | 2,106 | 53 | 100.00% | 73.61% | 84.80% | 100.00% (7/7 above-PM) |
## small (2,106 lines)
- round_amounts: recall 100.00%, precision 85.71%, F1 92.31% (6/6 caught, 1 false positives)
- entry_splitting: recall 100.00%, precision 90.00%, F1 94.74% (18/18 caught, 2 false positives)
- period_end: recall 100.00%, precision 50.00%, F1 66.67% (4/4 caught, 4 false positives)
- unusual_pairs: recall 100.00%, precision 100.00%, F1 100.00% (5/5 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 40.00%, F1 57.14% (4/4 caught, 6 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (3/3 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (6/6 caught, 0 false positives)
- date_divergence: recall 100.00%, precision 100.00%, F1 100.00% (4/4 caught, 0 false positives)
- high_risk_system_pairs: recall 100.00%, precision 30.00%, F1 46.15% (3/3 caught, 7 false positives)
- universe: 26 selected of 26 refs; 7/7 above-PM injected anomalies in universe (recall 100.00%)
