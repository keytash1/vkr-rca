# Milestone 8A results: Cross-Topology Generalization

M8A evaluates the frozen M7 model on controlled unseen graph structures. RCAEval, GNNs, temporal features and detector retuning are outside this milestone.

## Frozen M7 baseline

- Model: `m7-lambdamart-v1`
- SHA256: `3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699`
- Feature schema: `m7-v1`
- Frozen parameters: `{"colsample_bytree": 0.8, "eta": 0.1, "max_depth": 2, "min_child_weight": 1, "subsample": 0.8}`
- Training rounds: 1

The frozen model was trained only on Topology A (`gateway -> orders -> payment`). B and C were never used for model selection or M7 fitting.

## Benchmark systems

### Topology B: branch

- Services: billing, catalog, fulfillment, inventory, portal
- Entry: portal
- Edges: portal -> fulfillment, fulfillment -> billing, portal -> catalog, catalog -> inventory
- Dataset run: `m8a-b-full-seed-20260904-r2`
- Zero-shot faults: 500
- Healthy controls: 50
- Baseline operations: 5

### Topology C: parallel-shared

- Services: checkout, entry, journal, notifier, settlement, warehouse
- Entry: entry
- Edges: entry -> checkout, checkout -> settlement, checkout -> warehouse, checkout -> notifier, settlement -> journal, warehouse -> journal
- Dataset run: `m8a-c-full-seed-20260904-r2`
- Zero-shot faults: 600
- Healthy controls: 50
- Baseline operations: 6

## Zero-shot results

### Topology B

- Frozen model status: **STRONG_TRANSFER**
- Detection recall: 0.8240 (412/500)
- Healthy FPR: 0.1800
- Root-ready coverage: 1.0000
- Localization eligible: 412
- Non-trivial common subset: 384
- End-to-end AC@1: 0.7760
- Unexpected-branch anomaly rate: 0.0580

| Method | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|
| chance | 0.2211 | 0.6620 | 0.4826 |
| max_severity | 0.7344 | 0.9453 | 0.8390 |
| topology_consistency | 0.9245 | 0.9453 | 0.9345 |
| local_evidence | 0.8073 | 0.9453 | 0.8763 |
| hybrid_v1 | 0.9245 | 0.9453 | 0.9349 |
| m7_lambdamart_zero_shot | 0.9375 | 0.9922 | 0.9668 |

Paired frozen-LambdaMART minus hybrid: ΔAC@1=0.0130 95% CI [-0.0078, 0.0365]; ΔMRR=0.0319 95% CI [0.0124, 0.0521].

Ranking margin (an uncalibrated stability measure, not confidence):

- median: 0.19017578
- p10: 0.02153286
- exact zero fraction: 0.0521
- below epsilon fraction: 0.0521

### Topology C

- Frozen model status: **STRONG_TRANSFER**
- Detection recall: 0.8483 (509/600)
- Healthy FPR: 0.3400
- Root-ready coverage: 1.0000
- Localization eligible: 509
- Non-trivial common subset: 497
- End-to-end AC@1: 0.7983
- Unexpected-branch anomaly rate: 0.1433

| Method | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|
| chance | 0.1945 | 0.5542 | 0.4389 |
| max_severity | 0.5553 | 0.9054 | 0.6796 |
| topology_consistency | 0.8692 | 0.9115 | 0.8897 |
| local_evidence | 0.5573 | 0.9054 | 0.6802 |
| hybrid_v1 | 0.8652 | 0.9115 | 0.8877 |
| m7_lambdamart_zero_shot | 0.9396 | 0.9899 | 0.9644 |

Paired frozen-LambdaMART minus hybrid: ΔAC@1=0.0744 95% CI [0.0423, 0.1087]; ΔMRR=0.0767 95% CI [0.0509, 0.1030].

Ranking margin (an uncalibrated stability measure, not confidence):

- median: 0.19017578
- p10: 0.02153286
- exact zero fraction: 0.0885
- below epsilon fraction: 0.0885

## Temporal stress

### Topology B

| Profile | Incidents | Detection | Conditional AC@1 | AC@3 | MRR | End-to-end AC@1 |
|---|---:|---:|---:|---:|---:|---:|
| burst | 10 | 0.5000 | 1.0000 | 1.0000 | 1.0000 | 0.5000 |
| intermittent | 10 | 1.0000 | 0.8000 | 1.0000 | 0.9000 | 0.8000 |
| ramp | 10 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| step_early | 10 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| step_late | 10 | 0.9000 | 0.7778 | 1.0000 | 0.8889 | 0.7000 |

### Topology C

| Profile | Incidents | Detection | Conditional AC@1 | AC@3 | MRR | End-to-end AC@1 |
|---|---:|---:|---:|---:|---:|---:|
| burst | 12 | 0.5833 | 0.7143 | 0.8571 | 0.7976 | 0.4167 |
| intermittent | 12 | 0.7500 | 1.0000 | 1.0000 | 1.0000 | 0.7500 |
| ramp | 12 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| step_early | 12 | 1.0000 | 0.9167 | 1.0000 | 0.9583 | 0.9167 |
| step_late | 12 | 0.8333 | 1.0000 | 1.0000 | 1.0000 | 0.8333 |

## Repeated-run stability

- Topology B: 10 fixed scenarios, 50 runs; mean Top-1 consistency=0.9600; mean truth-rank variance=0.0240.
- Topology C: 10 fixed scenarios, 50 runs; mean Top-1 consistency=0.9800; mean truth-rank variance=0.0160.

Per-scenario ranks and variability of exclusive duration, latency-z and topology-f1 are retained in the checked-in evaluation JSON.

## Detection misses and healthy false positives

- Topology B miss classes: `{"below_threshold": 88}`
- Topology B false-positive cases: 9
- Topology C miss classes: `{"below_threshold": 91}`
- Topology C false-positive cases: 17

Full operation-level diagnostics are in `docs/m8a-false-positives.md` and the evaluation JSON.

## System-holdout matrix

The `m8a-lambdamart-cross-v1` folds reuse M7 hyperparameters and one training round. No held-out topology is used for tuning.

| Held out | Train systems | Train incidents | Test incidents | Frozen AC@1 | Cross AC@1 | Cross MRR |
|---|---|---:|---:|---:|---:|---:|
| A | B+C | 881 | 414 | 0.9348 | 0.9444 | 0.9690 |
| B | A+C | 911 | 384 | 0.9375 | 0.9688 | 0.9811 |
| C | A+B | 798 | 497 | 0.9396 | 0.9376 | 0.9628 |

## Feature distribution shift

Statistics are conditioned on non-trivial localization-eligible candidate rows.

| Feature | Strongest pair | Standardized median difference |
|---|---|---:|
| ancestor_ratio | B vs C | 0.6667 |
| descendant_ratio | A vs B | 0.3750 |
| topology_f1 | A vs B | 0.3704 |
| log1p_median_exclusive_duration_ms | A vs B | 0.2654 |
| latency_z_log1p | A vs B | 0.2373 |
| median_exclusive_ratio | B vs C | 0.0780 |
| error_z_log1p | A vs B | 0.0000 |
| in_degree | A vs B | 0.0000 |
| out_degree | A vs B | 0.0000 |

## Verdicts

- FEATURE REPRESENTATION: **TRANSFERABLE**
- M7 LAMBDAMART: **STRONG_TRANSFER**

Verdicts separate representation quality from the frozen learned ranker. They use conditional performance above chance, end-to-end detection-limited quality, paired comparisons and survival on both unseen graph structures; they are not claims of external-domain transfer.

## Limitations

1. All systems are controlled synthetic Go services with the same OTel instrumentation and fault injector.
2. B/C are structurally unseen, but this is not an external telemetry domain.
3. Faults remain single-root and limited to latency/error.
4. M5 thresholds are frozen; detector quality bounds end-to-end localization.
5. Temporal profiles are evaluated with aggregate M7 features; no temporal features were added.
6. `ml_score` and score margin are not probabilities or confidence estimates.
7. System-holdout models reuse the one-round M7 configuration and are not tuned for B/C.
8. RCAEval remains mandatory M8B work and was not downloaded or adapted here.

M8B was not started.
