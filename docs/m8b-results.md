# M8B — External Validation on RCAEval

## Locked corpus and integrity

All **240/240** pinned trace-capable cases were evaluated. Status counts: `{'detection_miss': 100, 'insufficient_baseline': 1, 'ready': 127, 'root_not_observable': 12}`. Predictions were sealed before labels were joined.

## Service-level zero-shot results

| Dataset | Cases | Recall | Healthy FPR | Root observable | Eligible | M7 AC@1 | M7 AC@3 | M7 MRR | E2E AC@1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RE2-OB | 90 | 57.8% | 0.0% | 100.0% | 52 | 21.2% | 73.1% | 43.4% | 12.2% |
| RE2-TT | 90 | 80.0% | 18.9% | 100.0% | 72 | 15.3% | 15.3% | 20.7% | 12.2% |
| RE3-OB | 30 | 10.0% | 0.0% | 60.0% | 3 | 0.0% | 100.0% | 33.3% | 0.0% |
| RE3-TT | 30 | 0.0% | 0.0% | 100.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| overall | 240 | 52.9% | 7.1% | 95.0% | 127 | 17.3% | 40.9% | 30.3% | 9.2% |

Healthy FPR rollups: OB=0.0%, TT=14.2%, RE2=9.4%, RE3=0.0%.

## M6 baselines and frozen M7 (overall, conditional)

| Method | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|
| chance | 8.6% | 25.8% | 24.9% |
| frozen_m7 | 17.3% | 40.9% | 30.3% |
| hybrid_v1 | 55.1% | 59.1% | 57.1% |
| local_evidence | 55.1% | 59.1% | 57.1% |
| max_severity | 48.0% | 55.9% | 52.6% |
| topology_consistency | 55.9% | 59.1% | 57.3% |

## Evidence coverage and score stability

| Dataset | Error evidence | Exclusive trace | Parent match | Margin median | Margin p10 | Exact ties | Near ties |
|---|---:|---:|---:|---:|---:|---:|---:|
| RE2-OB | 90.2% | 100.0% | 99.9% | 0.000000 | 0.000000 | 84.6% | 84.6% |
| RE2-TT | 0.0% | 98.9% | 98.1% | 0.000000 | 0.000000 | 83.3% | 83.3% |
| RE3-OB | 87.5% | 100.0% | 100.0% | 0.000000 | 0.000000 | 100.0% | 100.0% |
| RE3-TT | 0.0% | 100.0% | 100.0% | 0.000000 | 0.000000 | 0.0% | 0.0% |
| overall | 44.8% | 99.6% | 99.3% | 0.000000 | 0.000000 | 84.3% | 84.3% |

All emitted ready-candidate M7 vectors passed the finite numeric schema check (anomaly-feature coverage 100% within the localization universe). Error coverage is lower where source status is missing; topology and exclusive-trace coverage are therefore reported independently rather than filled with synthetic evidence.

## Fault-type breakdown

| Dataset:fault | Cases | Recall | Eligible | M7 AC@1 | M7 AC@3 | M7 MRR | E2E AC@1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| RE2-OB:cpu | 15 | 33.3% | 5 | 0.0% | 100.0% | 33.3% | 0.0% |
| RE2-OB:delay | 15 | 80.0% | 12 | 41.7% | 75.0% | 57.2% | 33.3% |
| RE2-OB:disk | 15 | 46.7% | 7 | 0.0% | 71.4% | 29.4% | 0.0% |
| RE2-OB:loss | 15 | 80.0% | 12 | 33.3% | 83.3% | 52.4% | 26.7% |
| RE2-OB:mem | 15 | 80.0% | 12 | 16.7% | 50.0% | 37.2% | 13.3% |
| RE2-OB:socket | 15 | 26.7% | 4 | 0.0% | 75.0% | 31.2% | 0.0% |
| RE2-TT:cpu | 15 | 93.3% | 14 | 7.1% | 7.1% | 13.9% | 6.7% |
| RE2-TT:delay | 15 | 93.3% | 14 | 35.7% | 35.7% | 40.3% | 33.3% |
| RE2-TT:disk | 15 | 60.0% | 9 | 0.0% | 0.0% | 5.4% | 0.0% |
| RE2-TT:loss | 15 | 60.0% | 9 | 0.0% | 0.0% | 5.0% | 0.0% |
| RE2-TT:mem | 15 | 93.3% | 14 | 7.1% | 7.1% | 13.7% | 6.7% |
| RE2-TT:socket | 15 | 80.0% | 12 | 33.3% | 33.3% | 36.9% | 26.7% |
| RE3-OB:f1 | 9 | 33.3% | 3 | 0.0% | 100.0% | 33.3% | 0.0% |
| RE3-OB:f2 | 3 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-OB:f3 | 6 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-OB:f4 | 6 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-OB:f5 | 6 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-TT:f1 | 7 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-TT:f2 | 7 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-TT:f3 | 10 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |
| RE3-TT:f4 | 6 | 0.0% | 0 | 0.0% | 0.0% | 0.0% | 0.0% |

## External system-holdout

RE2 models use the unchanged M7 feature schema, fixed M7 hyperparameters and rounds; RE3 is evaluation-only and out-of-fault-family.

- `train_RE2-OB_test_RE2-TT`: train=52; RE2-TT AC@1=0.153, MRR=0.331, RE3-OB AC@1=0.000, MRR=0.500, RE3-TT AC@1=0.000, MRR=0.000
- `train_RE2-TT_test_RE2-OB`: train=72; RE2-OB AC@1=0.442, MRR=0.698, RE3-OB AC@1=0.000, MRR=0.500, RE3-TT AC@1=0.000, MRR=0.000

## Official RCAEval baselines

TraceRCA was reproduced unmodified on the pinned RE2-OB smoke case (1.114 s; 35 native operation candidates). The full supported run uses the exact coarse service conversion in pinned `main.py` (split the operation token, strip `-db`, and stable-deduplicate); upstream method code is unchanged.

- tracerca: 189/240 succeeded; service AC@1=0.307, AC@3=0.608, MRR=0.497; mean runtime=1.483s.
- Explicit upstream compatibility failures: `{'KeyError': 41, 'TypeError': 10}` by exception and `{'RE2-TT': 19, 'RE3-OB': 2, 'RE3-TT': 30}` by dataset. Metrics above use only the 189 successful official runs and are not silently assigned scores for failures.
- BARO and Multi-source BARO require metric/multi-source inputs absent from the locked trace-only corpus and were not forced.
- MicroRank's pinned raw-trace path exceeded the 30-second smoke budget on one case; no upstream source was patched, and a partial full run is not reported.

## Feature shift

Largest standardized median shifts across synthetic A/B/C and external suites:

- `topology_f1`: C vs RE3-OB = 3.810
- `log1p_median_exclusive_duration_ms`: B vs RE3-TT = 3.517
- `in_degree`: B vs RE3-TT = 2.000
- `median_exclusive_ratio`: C vs RE2-OB = 1.752
- `ancestor_ratio`: C vs RE2-TT = 1.346
- `descendant_ratio`: B vs RE2-TT = 0.787
- `latency_z_log1p`: C vs RE3-TT = 0.785
- `out_degree`: A vs RE3-OB = 0.500
- `error_z_log1p`: A vs B = 0.000

## Verdicts

- **EXTERNAL ADAPTER:** PARTIAL_PARITY
- **FEATURE REPRESENTATION EXTERNAL:** STRONG_TRANSFER
- **FROZEN M7 EXTERNAL:** PARTIAL_TRANSFER
- **DETECTOR EXTERNAL:** LIMITING
- **NEXT MODEL DIRECTION:** KEEP LAMBDAMART, REDESIGN DETECTOR FIRST, ADD TEMPORAL FEATURES

Adapter parity is partial because native span kind is absent in every suite and status/error evidence is absent in Train Ticket; M5/M6 mathematics are reused directly and all missing evidence remains coverage-qualified.

The zero-shot result is preserved even when performance is weak; no detector, window, feature, or threshold was retuned.
