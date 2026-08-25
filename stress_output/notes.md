# JE Agent — Stress-Test Results (labeled anomalies)

Generated 2026-08-25 15:42 · total run time 4.9s · deterministic rules (LLM triage leg optional, `--skip-triage` not used if you ran with it).

Method: synthetic journal populations with **known injected anomalies** (round amounts, split-below-materiality invoices, period-end postings, unusual account pairs, rare users, unbalanced docs, reversals). Every injected document carries its label; each rule is scored against it.

## Aggregate

| Scenario | Lines | Injections | Recall | Precision | F1 |
|---|---|---|---|---|---|
| small | 2,092 | 46 | 100.00% | 4.40% | 8.42% |
## small (2,092 lines)
- round_amounts: recall 100.00%, precision 100.00%, F1 100.00% (6/6 caught, 0 false positives)
- entry_splitting: recall 100.00%, precision 100.00%, F1 100.00% (18/18 caught, 0 false positives)
- period_end: recall 100.00%, precision 100.00%, F1 100.00% (4/4 caught, 0 false positives)
- unusual_pairs: recall 100.00%, precision 100.00%, F1 100.00% (5/5 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 100.00%, F1 100.00% (4/4 caught, 0 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (3/3 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (6/6 caught, 0 false positives)
