# M10A — Research Freeze & Claim Validation

M10A introduces no new model, feature, telemetry source, threshold, or runtime behavior. It validates the immutable M9B research core with fixed denominators and deterministic statistics.

## Matched multimodal fusion claim

| Scope | Cases | All AC@1 | Metrics AC@1 | ΔAC@1 (95% CI) | ΔMRR (95% CI) | Inference |
|---|---:|---:|---:|---:|---:|---|
| Overall | 216 | 70.4% | 64.4% | +0.060 [+0.000, +0.120] | +0.038 [+0.005, +0.072] | paired bootstrap |
| RE2-OB | 90 | 73.3% | 74.4% | -0.011 [-0.111, +0.089] | -0.011 [-0.069, +0.046] | paired_bootstrap |
| RE2-TT | 90 | 60.0% | 43.3% | +0.167 [+0.089, +0.256] | +0.106 [+0.058, +0.158] | paired_bootstrap |
| RE3-OB | 6 | 50.0% | 50.0% | +0.000 [-0.500, +0.500] | +0.028 [-0.222, +0.264] | descriptive_small_n |
| RE3-TT | 30 | 96.7% | 100.0% | -0.033 [-0.100, +0.000] | -0.017 [-0.050, +0.000] | paired_bootstrap |

Fusion conclusion: **PARTIALLY SUPPORTED / METRIC-DEPENDENT**. The AC@1 gain is not statistically stable because its interval touches zero, while the MRR gain is statistically supported. The point estimates remain reported. RE3-OB is descriptive only (`n=6`), and the suite rows show that the gain is domain-dependent.

## Metric model denominators

| Dataset | Conditional cases | Conditional AC@1 | Full cases | Missing-root failures | Full AC@1 | Full AC@3 | Full MRR |
|---|---:|---:|---:|---:|---:|---:|---:|
| RE2-OB | 90 | 88.9% | 90 | 0 | 88.9% | 100.0% | 94.3% |
| RE2-SS | 90 | 95.6% | 90 | 0 | 95.6% | 98.9% | 97.5% |
| RE2-TT | 90 | 72.2% | 90 | 0 | 72.2% | 94.4% | 84.1% |
| RE3-OB | 6 | 33.3% | 30 | 24 | 6.7% | 13.3% | 11.3% |
| RE3-SS | 30 | 53.3% | 30 | 0 | 53.3% | 83.3% | 70.7% |
| RE3-TT | 30 | 86.7% | 30 | 0 | 86.7% | 100.0% | 93.3% |
| Overall | 336 | 81.8% | 360 | 24 | 76.4% | 89.7% | 83.6% |

Conditional and full-denominator results are intentionally separate. An unobservable root is a rank-zero failure in the 360-case result.

## Fair BARO comparison

- Comparable: `True`.
- Same incident IDs: `True`.
- Same root labels: `True`.
- Granularity: M9B `service`; BARO `official coarse service projection`.
- Candidate universes differ by method, but both produce service-level ranks for the same target and incidents.

| Method | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| M9B metric LambdaMART | 360 | 76.4% | 89.7% | 83.6% |
| Pinned BARO | 360 | 32.2% | 87.2% | 60.4% |

Paired M9B−BARO: ΔAC@1 +0.442 [+0.381, +0.503]; ΔMRR +0.232 [+0.192, +0.271].

## Robustness to learner randomness

Five deterministic XGBoost seeds reuse the frozen folds, hyperparameters, rounds, and feature schemas.

### RE1 metric system holdouts

| Fold | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |
|---|---:|---:|---:|---:|---:|---:|
| OB+SS | 0.544±0.034 | 0.496–0.584 | [0.514, 0.573] | 0.672±0.022 | 0.639–0.704 | [0.652, 0.691] |
| OB+TT | 0.933±0.004 | 0.928–0.936 | [0.930, 0.936] | 0.966±0.002 | 0.963–0.968 | [0.964, 0.968] |
| SS+TT | 0.790±0.006 | 0.780–0.797 | [0.785, 0.795] | 0.872±0.002 | 0.869–0.876 | [0.870, 0.874] |

Across-fold mean per seed:

| Scope | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 0.756±0.012 | 0.737–0.770 | [0.744, 0.766] | 0.837±0.008 | 0.825–0.848 | [0.830, 0.843] |

### RE2 multi-source cross-system folds

| Fold | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |
|---|---:|---:|---:|---:|---:|---:|
| train_RE2-OB_test_TT | 0.549±0.050 | 0.467–0.600 | [0.504, 0.591] | 0.672±0.035 | 0.618–0.712 | [0.642, 0.702] |
| train_RE2-TT_test_OB | 0.740±0.022 | 0.711–0.778 | [0.722, 0.762] | 0.855±0.012 | 0.835–0.872 | [0.843, 0.865] |

Across-fold mean per seed:

| Scope | AC@1 mean±std | min–max | 95% CI mean | MRR mean±std | min–max | 95% CI mean |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 0.644±0.030 | 0.600–0.672 | [0.617, 0.669] | 0.763±0.019 | 0.737–0.784 | [0.747, 0.780] |

## Feature-group stability

Importance is normalized XGBoost total gain. `cross_family` contains metric availability and aggregate/percentile summary features. Importance is predictive, not causal responsibility.

### metric_models

| Group | Mean share | Min | Max | Present | Status |
|---|---:|---:|---:|---:|---|
| cpu | 39.2% | 15.3% | 53.3% | 100.0% | domain_dependent |
| memory | 2.5% | 1.1% | 5.9% | 100.0% | low_or_unused |
| disk | 0.0% | 0.0% | 0.0% | 0.0% | low_or_unused |
| socket | 0.0% | 0.0% | 0.0% | 0.0% | low_or_unused |
| workload | 2.2% | 0.8% | 3.4% | 100.0% | low_or_unused |
| error | 0.2% | 0.0% | 0.9% | 25.0% | domain_dependent |
| latency | 43.6% | 20.4% | 77.4% | 100.0% | domain_dependent |
| trace | 0.0% | 0.0% | 0.0% | 0.0% | low_or_unused |
| topology | 0.0% | 0.0% | 0.0% | 0.0% | low_or_unused |
| cross_family | 12.3% | 0.6% | 38.5% | 100.0% | domain_dependent |

### multisource_models

| Group | Mean share | Min | Max | Present | Status |
|---|---:|---:|---:|---:|---|
| cpu | 29.8% | 8.4% | 51.1% | 100.0% | domain_dependent |
| memory | 5.6% | 0.0% | 11.2% | 50.0% | domain_dependent |
| disk | 0.3% | 0.0% | 0.7% | 50.0% | domain_dependent |
| socket | 6.6% | 0.0% | 13.2% | 50.0% | domain_dependent |
| workload | 0.1% | 0.0% | 0.1% | 50.0% | domain_dependent |
| error | 0.0% | 0.0% | 0.0% | 0.0% | low_or_unused |
| latency | 38.1% | 16.4% | 59.8% | 100.0% | domain_dependent |
| trace | 9.6% | 3.7% | 15.5% | 100.0% | stable_important |
| topology | 2.5% | 2.4% | 2.6% | 100.0% | low_or_unused |
| cross_family | 7.4% | 0.0% | 14.8% | 50.0% | domain_dependent |

## Research freeze decision

The M9B implementation and conclusions contain no discovered mathematical or implementation error. The final research architecture is frozen. No GNN, causal method, log modality, detector-v3, feature family, or new ranker is started in M10A.
