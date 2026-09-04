# M9A — Temporal Anomaly Detector v2

## Frozen configuration

Selected on synthetic validation only: `{'variant': 'cusum', 'windows': (5, 10, 20), 'tail_quantile': 0.9, 'cusum_k': 0.25, 'location_threshold': 2.5, 'tail_threshold': 4.0, 'cusum_threshold': 20.0, 'error_threshold': 3.0, 'epsilon': 0.1}`.

Config SHA256: `ad13f50171a21198bfda8ade4165ba0d03c1c5912a335346b22ad3ea456bf048`. RCAEval labels were not used for selection.

The CUSUM family was selected from 91 fixed candidates: it reached the maximum synthetic-validation recall at zero healthy FPR and won the tie against the combined detector on lower complexity.

### Candidate-family comparison

| Family | Best validation recall | Healthy FPR |
|---|---:|---:|
| multiscale_location | 76.7% | 0.0% |
| multiscale_location_tail | 100.0% | 0.0% |
| cusum | 100.0% | 0.0% |
| combined_temporal_v2 | 100.0% | 0.0% |

## Synthetic validation

| Detector | Recall | Healthy FPR |
|---|---:|---:|
| M5/v1 | 59.3% | 0.0% |
| detector-v2 | 100.0% | 0.0% |

### Temporal profiles

| Profile | v1 detection | v2 detection |
|---|---:|---:|
| healthy | 0.0% | 0.0% |
| constant | 100.0% | 100.0% |
| step_early | 100.0% | 100.0% |
| step_late | 95.0% | 100.0% |
| ramp | 100.0% | 100.0% |
| intermittent | 0.0% | 100.0% |
| burst | 0.0% | 100.0% |

### Topology and repeatability

| Topology | v1 recall | v2 recall | v1 FPR | v2 FPR |
|---|---:|---:|---:|---:|
| A | 69.2% | 100.0% | 0.0% | 0.0% |
| B | 64.4% | 100.0% | 0.0% | 0.0% |
| C | 37.5% | 100.0% | 0.0% | 0.0% |

Across five deterministic repetitions per scenario, v1 had 1 inconsistent scenarios (detection-rate variance 0.2418); v2 had 0 (variance 0.1963).


## Post-M8B frozen-detector-v2 external evaluation

This is not a new pristine zero-shot benchmark: M8B had already been inspected. Configuration was frozen first on synthetic data.

| Dataset | v1 recall | v2 recall | Difference | v1 FPR | v2 FPR | v1 root | v2 root |
|---|---:|---:|---:|---:|---:|---:|---:|
| RE2-OB | 57.8% | 100.0% | 42.2% | 0.0% | 100.0% | 32.2% | 100.0% |
| RE2-TT | 80.0% | 98.9% | 18.9% | 18.9% | 98.9% | 51.1% | 98.9% |
| RE3-OB | 10.0% | 100.0% | 90.0% | 0.0% | 100.0% | 0.0% | 13.3% |
| RE3-TT | 0.0% | 100.0% | 100.0% | 0.0% | 100.0% | 0.0% | 100.0% |
| overall | 52.9% | 99.6% | 46.7% | 7.1% | 99.6% | 31.2% | 88.8% |

Paired external detection: {"both_negative": 1, "both_positive": 127, "exact_mcnemar_p": 3.851859888774472e-34, "v1_only": 0, "v2_only": 112}.

Recall-difference paired bootstrap 95% CI: [0.404, 0.529].

Paired healthy controls: {"both_negative": 1, "both_positive": 17, "exact_mcnemar_p": 2.967364920549937e-67, "v1_only": 0, "v2_only": 222}.

FPR-difference paired bootstrap 95% CI: [0.887, 0.958].

## Per-fault results

| Dataset:fault | v1 recall | v2 recall | Difference | v2 FPR |
|---|---:|---:|---:|---:|
| RE2-OB:cpu | 33.3% | 100.0% | 66.7% | 100.0% |
| RE2-OB:delay | 80.0% | 100.0% | 20.0% | 100.0% |
| RE2-OB:disk | 46.7% | 100.0% | 53.3% | 100.0% |
| RE2-OB:loss | 80.0% | 100.0% | 20.0% | 100.0% |
| RE2-OB:mem | 80.0% | 100.0% | 20.0% | 100.0% |
| RE2-OB:socket | 26.7% | 100.0% | 73.3% | 100.0% |
| RE2-TT:cpu | 93.3% | 100.0% | 6.7% | 100.0% |
| RE2-TT:delay | 93.3% | 100.0% | 6.7% | 100.0% |
| RE2-TT:disk | 60.0% | 100.0% | 40.0% | 100.0% |
| RE2-TT:loss | 60.0% | 100.0% | 40.0% | 100.0% |
| RE2-TT:mem | 93.3% | 100.0% | 6.7% | 100.0% |
| RE2-TT:socket | 80.0% | 93.3% | 13.3% | 93.3% |
| RE3-OB:f1 | 33.3% | 100.0% | 66.7% | 100.0% |
| RE3-OB:f2 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-OB:f3 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-OB:f4 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-OB:f5 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-TT:f1 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-TT:f2 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-TT:f3 | 0.0% | 100.0% | 100.0% | 100.0% |
| RE3-TT:f4 | 0.0% | 100.0% | 100.0% | 100.0% |

## RE3 and diagnostic studies

RE3-OB/TT incident recall rose to 100.0%/100.0%, but both healthy FPR values are 100.0%. The apparent recall is therefore not usable evidence of code-fault sensitivity.

Detector-v2 produced 239 false-positive healthy controls and 1 fault miss. Case-level scores and causes are in `m9a-false-positives.md` and `m9a-detection-misses.md`.

The label-blind metrics audit found timestamped service/entity CPU, memory, disk I/O, socket, workload, error and latency fields. These metrics were not consumed by detector-v2.

## Limitations

- Synthetic sequences contain 60 current observations, while external operations often contain thousands; the selected cumulative score is not length-normalized.
- Positive-only residuals have a positive healthy expectation, so an unbounded CUSUM can accumulate ordinary workload variation.
- RCAEval Train Ticket status evidence is unavailable; its error temporal channel is explicitly unavailable rather than treated as healthy.
- Pseudo-healthy windows are pre-injection controls from fault recordings, not independent production incidents.
- This post-M8B evaluation is not a pristine zero-shot benchmark and does not alter M8B.

## Verdict

**NOT_JUSTIFIED**

Recommendation: **REDESIGN AGAIN**.

The recall gain fails the pre-registered healthy-FPR gate. Do not promote detector-v2 or feed its output into RCA ranking. A next design must address sequence-length calibration and external healthy drift before considering multi-source ranking.

M5/v1 and all M8B artifacts remain unchanged. M9A does not modify RCA ranking or train M7.
