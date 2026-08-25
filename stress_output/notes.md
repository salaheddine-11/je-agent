# JE Agent — Stress-Test Results (labeled anomalies)

Generated 2026-08-25 16:29 · total run time 148.7s · deterministic rules (LLM triage leg optional, `--skip-triage` not used if you ran with it).

Method: synthetic journal populations with **known injected anomalies** (round amounts, split-below-materiality invoices, period-end postings, unusual account pairs, rare users, unbalanced docs, reversals). Every injected document carries its label; each rule is scored against it.

## Aggregate

| Scenario | Lines | Injections | Recall | Precision | F1 |
|---|---|---|---|---|---|
| medium | 20,210 | 105 | 100.00% | 18.88% | 31.77% |
| large | 100,354 | 177 | 98.87% | 6.67% | 12.50% |
| huge | 200,562 | 281 | 98.93% | 6.43% | 12.07% |
## medium (20,210 lines)
- round_amounts: recall 100.00%, precision 27.27%, F1 42.86% (30/30 caught, 80 false positives)
- entry_splitting: recall 100.00%, precision 4.81%, F1 9.17% (86/86 caught, 1703 false positives)
- period_end: recall 100.00%, precision 6.34%, F1 11.92% (18/18 caught, 266 false positives)
- unusual_pairs: recall 96.15%, precision 100.00%, F1 98.04% (25/26 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 100.00%, F1 100.00% (18/18 caught, 0 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (15/15 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (40/40 caught, 0 false positives)
- date_divergence: recall 86.67%, precision 100.00%, F1 92.86% (26/30 caught, 0 false positives)
- high_risk_system_pairs: recall 100.00%, precision 0.89%, F1 1.76% (18/18 caught, 2005 false positives)

## large (100,354 lines)
- round_amounts: recall 100.00%, precision 30.30%, F1 46.51% (20/20 caught, 46 false positives)
- entry_splitting: recall 100.00%, precision 6.10%, F1 11.51% (55/55 caught, 846 false positives)
- period_end: recall 100.00%, precision 6.82%, F1 12.77% (12/12 caught, 164 false positives)
- unusual_pairs: recall 100.00%, precision 100.00%, F1 100.00% (18/18 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 100.00%, F1 100.00% (12/12 caught, 0 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (10/10 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (24/24 caught, 0 false positives)
- date_divergence: recall 87.50%, precision 100.00%, F1 93.33% (14/16 caught, 0 false positives)
- high_risk_system_pairs: recall 100.00%, precision 0.71%, F1 1.41% (10/10 caught, 1399 false positives)

## huge (200,562 lines)
- round_amounts: recall 100.00%, precision 27.27%, F1 42.86% (30/30 caught, 80 false positives)
- entry_splitting: recall 100.00%, precision 4.81%, F1 9.17% (86/86 caught, 1703 false positives)
- period_end: recall 100.00%, precision 6.34%, F1 11.92% (18/18 caught, 266 false positives)
- unusual_pairs: recall 96.15%, precision 100.00%, F1 98.04% (25/26 caught, 0 false positives)
- unusual_users: recall 100.00%, precision 100.00%, F1 100.00% (18/18 caught, 0 false positives)
- balance_check: recall 100.00%, precision 100.00%, F1 100.00% (15/15 caught, 0 false positives)
- reversals: recall 100.00%, precision 100.00%, F1 100.00% (40/40 caught, 0 false positives)
- date_divergence: recall 86.67%, precision 100.00%, F1 92.86% (26/30 caught, 0 false positives)
- high_risk_system_pairs: recall 100.00%, precision 0.89%, F1 1.76% (18/18 caught, 2005 false positives)
