# Milestone 7 results: Dataset + Learning-to-Rank v1

This report records the first learned RCA experiment. It is a same-system research result, not evidence of arbitrary cross-system generalization.

## Reproducibility

- Dataset run: m7-full-seed-20260904
- Source Git commit: 36c23e837db444c2f4c52559678db7b8ed89977b
- Dataset schema: m7-v1
- Source feature schema: m6-v1
- Random seed: 20260904
- Python: 3.14.5
- XGBoost: 3.2.0
- NumPy: 2.4.4
- Features SHA256: 716acd3aef75fe8bf429143b7526e7368d2598bcba910b5dad20cb1d10fe9b79
- Labels SHA256: 7712d2df05b83e8560e735afaa17b01b7f204b6775b9f8ad3e6647e692a415dc

The raw features.jsonl and labels.jsonl were written independently. Root service, fault type, and intensity exist only in labels. The join occurred by incident_id after truth-free M6 feature extraction.

Collector isolation uses a drain interval, a current-window reset, and a poll proving every operation has zero current samples before the next incident.

## Dataset

- Fault incidents: 600
- Healthy controls: 60
- Split incidents: train=327, validation=68, test=76
- Detection recall: 78.50%
- Root-ready coverage: 100.00%
- Training eligibility: 69.00%
- Healthy false-positive rate: 13.33%
- Localization eligible: 471
- Non-trivial training eligible: 414
- Trivial one-service groups: 57

Fault intensity distribution:

| Root | Fault | Count | Min | Median | Max |
|---|---|---:|---:|---:|---:|
| gateway | error | 100 | 0.111813 | 0.572565 | 0.990818 |
| gateway | latency | 100 | 1 | 17.5 | 697 |
| orders | error | 100 | 0.12419 | 0.555532 | 0.996102 |
| orders | latency | 100 | 1 | 22.5 | 693 |
| payment | error | 100 | 0.102876 | 0.530187 | 0.994221 |
| payment | latency | 100 | 1 | 22 | 612 |

## Numeric feature schema

The model uses an explicit ordered whitelist. Service and operation names, identifiers, scenario metadata, fault data, M6 rank positions, and truth are not model inputs.

~~~text
latency_z_log1p
error_z_log1p
latency_strength
error_strength
latency_anomalous
error_anomalous
m5_severity_log1p
topology_precision
topology_recall
topology_f1
local_evidence
trace_coverage
median_exclusive_ratio
median_downstream_wait_ratio
log1p_median_exclusive_duration_ms
active_topology_trace_coverage
is_observed_anomaly
expected_affected_count
expected_affected_ratio
ready_universe_size
observed_anomaly_count
observed_anomaly_ratio
primary_signal_latency
primary_signal_error
topology_source_active
in_degree
out_degree
normalized_in_degree
normalized_out_degree
ancestor_count
descendant_count
ancestor_ratio
descendant_ratio
~~~

Feature groups:

- ANOMALY: latency_z_log1p, error_z_log1p, latency_strength, error_strength, latency_anomalous, error_anomalous, m5_severity_log1p, is_observed_anomaly
- TOPOLOGY: topology_precision, topology_recall, topology_f1, expected_affected_count, expected_affected_ratio, in_degree, out_degree, normalized_in_degree, normalized_out_degree, ancestor_count, descendant_count, ancestor_ratio, descendant_ratio
- TRACE: local_evidence, trace_coverage, median_exclusive_ratio, median_downstream_wait_ratio, log1p_median_exclusive_duration_ms
- GLOBAL: active_topology_trace_coverage, ready_universe_size, observed_anomaly_count, observed_anomaly_ratio, primary_signal_latency, primary_signal_error, topology_source_active

## Model selection

LambdaMART uses XGBoost rank:ndcg, hist, binary relevance, incident query groups, top-k pair construction with three pairs per sample, and deterministic seeds. Test labels were not used for selection or fitting.

- Search candidates: 8
- Selected parameters: {"colsample_bytree": 0.8, "eta": 0.1, "max_depth": 2, "min_child_weight": 1, "subsample": 0.8}
- Best iteration: 0
- Final rounds on train + validation: 1
- Best validation metrics: {"ac_at_1": 1.0, "ac_at_3": 1.0, "mrr": 1.0, "ndcg_at_1": 1.0, "ndcg_at_3": 1.0}

## Non-trivial test comparison

All methods below use the same 68 incidents.

| Method | AC@1 | AC@3 | MRR | NDCG@1 | NDCG@3 |
|---|---:|---:|---:|---:|---:|
| chance | 0.3529 | 1.0000 | 0.6275 | 0.3529 | 0.7227 |
| max_severity | 0.4706 | 0.9706 | 0.6838 | 0.4706 | 0.7572 |
| topology_consistency | 0.9118 | 0.9706 | 0.9412 | 0.9118 | 0.9489 |
| local_evidence | 0.4853 | 0.9706 | 0.6912 | 0.4853 | 0.7626 |
| hybrid_v1 | 0.9265 | 0.9706 | 0.9485 | 0.9265 | 0.9543 |
| m7_lambdamart | 0.9265 | 1.0000 | 0.9632 | 0.9265 | 0.9729 |

## Conditional and end-to-end quality

- Test localization subset, including trivial groups: n=76, AC@1=0.9342, MRR=0.9671.
- Test non-trivial localization subset: n=68.
- End-to-end AC@1 over every injected fault incident: 0.7400.

## Paired bootstrap

The unit is one test incident. Intervals are deterministic 95% bootstrap CIs over 2000 paired resamples; no statistical-significance claim is made.

| Baseline | Delta AC@1 | 95% CI | Delta MRR | 95% CI |
|---|---:|---:|---:|---:|
| max_severity | 0.4559 | [0.3235, 0.5882] | 0.2794 | [0.2034, 0.3554] |
| topology_consistency | 0.0147 | [-0.0441, 0.0735] | 0.0221 | [-0.0147, 0.0662] |
| local_evidence | 0.4412 | [0.2941, 0.5735] | 0.2721 | [0.1863, 0.3480] |
| hybrid_v1 | 0.0000 | [-0.0588, 0.0588] | 0.0147 | [-0.0221, 0.0588] |

## Leakage sanity checks

- Real-label AC@1: 0.9265
- Permuted-label AC@1: 0.0000
- Chance AC@1: 0.3529
- Permutation sanity passed: true
- Schema tests prove the feature whitelist does not intersect forbidden metadata.
- Candidate service renaming leaves the numeric matrix unchanged; only an exact-score lexical tie may change presentation order.

## Leave-one-root-out

These folds hold out root identity inside the same topology. They are not cross-topology validation.

| Held-out root | Test incidents | Detection coverage | AC@1 | MRR |
|---|---:|---:|---:|---:|
| gateway | 81 | 0.6900 | 0.8148 | 0.9074 |
| orders | 140 | 0.7000 | 0.9071 | 0.9524 |
| payment | 193 | 0.9650 | 0.8808 | 0.9257 |

## Gain importance

Gain importance describes this fitted tree ensemble; it is not causal attribution.

| Feature | Gain |
|---|---:|
| topology_f1 | 109.252 |
| log1p_median_exclusive_duration_ms | 53.2844 |
| active_topology_trace_coverage | 0 |
| ancestor_count | 0 |
| ancestor_ratio | 0 |
| descendant_count | 0 |
| descendant_ratio | 0 |
| error_anomalous | 0 |
| error_strength | 0 |
| error_z_log1p | 0 |
| expected_affected_count | 0 |
| expected_affected_ratio | 0 |

## Per-incident examples

### payment latency - m7-00018

- Ranking: 1. orders (0.073141), 2. payment (0.073141), 3. gateway (-0.095502)
- Largest root-row TreeSHAP contributions: log1p_median_exclusive_duration_ms=0.1069, topology_f1=-0.035705, active_topology_trace_coverage=0, ancestor_count=0, ancestor_ratio=0
- TreeSHAP explains model score, not causality.

### orders error - m7-00114

- Ranking: 1. orders (0.094674), 2. gateway (-0.095502)
- Largest root-row TreeSHAP contributions: topology_f1=0.10309, log1p_median_exclusive_duration_ms=-0.010357, active_topology_trace_coverage=0, ancestor_count=0, ancestor_ratio=0
- TreeSHAP explains model score, not causality.

## Live deterministic scenarios

| Scenario | Truth rank | Ranking |
|---|---:|---|
| gateway-latency | 1 | 1. gateway, 2. payment, 3. orders |
| orders-latency | 1 | 1. orders, 2. gateway, 3. payment |
| payment-latency | 1 | 1. payment, 2. gateway, 3. orders |
| gateway-error | 1 | 1. gateway |
| orders-error | 1 | 1. orders, 2. gateway |
| payment-error | 1 | 1. payment, 2. gateway, 3. orders |

The first live pass placed Orders latency at rank 2 behind Payment; subsequent identical 700 ms live runs placed Orders at rank 1. This timing-sensitive variation is retained as an unexpected result: the selected model contains one shallow tree, and candidates can receive equal scores whose displayed order then follows the lexical tie-break. No ranking was edited manually.

## Limitations

1. All training telemetry comes from one three-service topology.
2. Repeated observations from one system do not prove cross-system transfer.
3. Faults are synthetic and single-root.
4. Only latency and error fault families are represented.
5. ml_score is a ranking score, not a probability or calibrated confidence.
6. XGBoost gain and TreeSHAP are not causal attribution.
7. M5 detection quality upper-bounds end-to-end localization.
8. Trace instrumentation completeness affects exclusive-duration features.
9. Cross-topology and external benchmark evaluation are mandatory M8 work.

## Candidate decision

**LEARNED MODEL CANDIDATE STATUS: PROMISING**

M8 was not started.
