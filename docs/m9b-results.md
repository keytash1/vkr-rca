# M9B — Multi-source Soft-Evidence RCA v2

M9B separates incident detection from localization. The primary table is externally triggered and has no hard anomaly gate. M5/v1 is retained only in the secondary autonomous table; rejected M9A detector-v2 is not used.

## RE1 metric model system holdout

| Fold | Train cases | Test | Cases | AC@1 | AC@3 | MRR |
|---|---:|---|---:|---:|---:|---:|
| OB+SS | 248 | RE1-TT | 125 | 51.2% | 77.6% | 66.1% |
| OB+TT | 248 | RE1-SS | 125 | 93.6% | 100.0% | 96.8% |
| SS+TT | 250 | RE1-OB | 123 | 78.9% | 96.7% | 87.1% |

Frozen metric hyperparameters: `{'colsample_bytree': 0.8, 'eta': 0.1, 'max_depth': 3, 'min_child_weight': 1, 'subsample': 0.8}`, rounds `23`. Final RE1 cases: `373`; model SHA256 `5d4d56f058286005fa1e4dadfeb62cea2b57373b3607abd1bcca41472795a615`.

## Frozen metric-only RE2/RE3 evaluation

| Dataset | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| RE2-OB | 90 | 88.9% | 100.0% | 94.3% |
| RE2-SS | 90 | 95.6% | 98.9% | 97.5% |
| RE2-TT | 90 | 72.2% | 94.4% | 84.1% |
| RE3-OB | 6 | 33.3% | 66.7% | 56.7% |
| RE3-SS | 30 | 53.3% | 83.3% | 70.7% |
| RE3-TT | 30 | 86.7% | 100.0% | 93.3% |
| overall | 336 | 81.8% | 96.1% | 89.6% |

## Triggered trace-capable evaluation

| Method | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| chance | 216 | 9.0% | 27.0% | 26.0% |
| m9b_metric_lambdamart | 216 | 80.1% | 96.8% | 88.9% |
| metric_max_shift | 216 | 50.0% | 67.1% | 61.3% |
| metric_top2 | 216 | 49.5% | 67.1% | 61.0% |
| rank_fusion_v1 | 216 | 40.3% | 77.8% | 60.1% |
| soft_hybrid_v1 | 216 | 30.6% | 57.9% | 47.4% |
| soft_topology_v1 | 216 | 18.5% | 50.0% | 37.8% |
| soft_trace_v1 | 216 | 29.2% | 56.0% | 47.7% |
| m9b_multisource_lambdamart | 216 | 70.4% | 89.4% | 80.6% |

Historical M6/M7 figures below use the older hard-gated eligible subset and are references, not direct comparisons with the all-candidate triggered table:

| Historical method | Eligible cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| frozen_m7 | 127 | 17.3% | 40.9% | 30.3% |
| hybrid_v1 | 127 | 55.1% | 59.1% | 57.1% |
| local_evidence | 127 | 55.1% | 59.1% | 57.1% |
| max_severity | 127 | 48.0% | 55.9% | 52.6% |
| topology_consistency | 127 | 55.9% | 59.1% | 57.3% |

### Per suite

| Dataset | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| RE2-OB | 90 | 73.3% | 97.8% | 84.8% |
| RE2-TT | 90 | 60.0% | 76.7% | 71.2% |
| RE3-OB | 6 | 50.0% | 100.0% | 69.4% |
| RE3-TT | 30 | 96.7% | 100.0% | 98.3% |

Best M9B method: `m9b_metric_lambdamart`. Best trace-only baseline: `soft_hybrid_v1`.

Paired ΔAC@1 `0.495`, 95% CI `[0.403, 0.579]`; ΔMRR `0.414`, 95% CI `[0.351, 0.474]`.

## Secondary autonomous M5/v1 mode

| Detector | Cases | Detection recall | Healthy FPR | End-to-end AC@1 |
|---|---:|---:|---:|---:|
| frozen M5/v1 | 240 | 52.9% | 7.1% | 34.6% |

## Verdict

**STRONG_MULTISOURCE_GAIN** using `m9b_metric_lambdamart`.

Code-fault coverage: **IMPROVED**.

Recommendation: **KEEP MULTISOURCE LAMBDAMART**.

The RE1-trained metric ranker is the strongest individual M9B method. Under the matched RE2 cross-system training protocol, however, all modalities improve AC@1 over its metrics-only ablation by `0.060`; this supports retaining the multi-source architecture while expanding cross-system training coverage, without escalating to GNN/causal/log models yet.

M9A remains `NOT_JUSTIFIED`: its trace-only CUSUM failed because of sequence-length/domain calibration and is not part of M9B.

## Limitations

- This is a post-M8B benchmark; only RE1 model selection is isolated from the previously inspected RE2/RE3 outcomes.
- Metric-only services are deterministic telemetry entities, while infrastructure/database entities are intentionally excluded from service-level ranking.
- Trigger timestamps are supplied externally; primary localization metrics do not measure incident detection.
- TreeSHAP/prediction contributions explain model score association, not causal responsibility.
- Official methods with incompatible upstream inputs/runtimes remain explicit rather than patched or silently approximated.
