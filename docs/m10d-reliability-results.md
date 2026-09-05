# M10D-A: cross-domain reliability v2 results

## Verdict

`REJECTED`

Reliability v2 is not promoted. None of the six preregistered methods passed the nested RE1 development gate. The frozen fallback was isotonic calibration; its later post-M10C external 90% policy accepted 95.56% of cases but achieved only 81.10% selective AC@1. This is another clear threshold-transfer failure, not a reason to retune the external threshold.

M10C remains a frozen challenger ranker. M10A remains the thesis Champion. The independent M10C conformal outputs remain valid and unchanged.

## Locked protocol

The protocol in `docs/m10d-reliability-protocol.md` and machine-readable `ml/models/m10d-reliability/protocol.json` was written before the external run. Development used outer system holdouts over RE1 Online Boutique, Sock Shop, and Train Ticket, inner OOF ranker/expert predictions, disjoint reliability fit/calibration partitions, and five seeds (`20260906..20260910`). The already-inspected RE2/RE3 360 cases did not select a method, threshold, feature, hyperparameter, or gate.

No reliability model receives service, system, dataset, fault, root, or case semantics. The incident ID is an opaque routing key, and `top1_service` is output metadata rather than a feature. The versioned inference table contains neither `top1_correct` nor truth rank.

## Cross-system development

The 90% target was the promotion target. Means below are over 15 outer-fold/seed evaluations; minimum-system AC@1 is the worst of the three system-specific five-seed means. A no-accept fold is conservatively scored as zero accuracy.

| Method | Selective AC@1 mean | Std | Coverage mean | Std | Minimum-system AC@1 | AURC mean | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Margin | 85.26% | 9.61 pp | 78.72% | 12.91 pp | 73.71% | 0.0756 | fail |
| Isotonic | **86.39%** | 10.35 pp | 72.75% | 16.95 pp | 73.90% | 0.0818 | fail |
| Logistic | 82.22% | 8.66 pp | 90.03% | 9.73 pp | 71.08% | 0.1224 | fail |
| Bounded monotonic boosting | 83.48% | 8.34 pp | 83.15% | 12.65 pp | 73.47% | 0.0900 | fail |
| Wilson risk control | 51.71% | 43.06 pp | 44.96% | 38.88 pp | 39.08% | 0.1224 | fail |
| Mondrian logistic | 83.20% | 9.17 pp | 87.25% | 11.48 pp | 71.43% | 0.1224 | fail |

The fallback rule therefore froze isotonic: highest mean held-out accuracy, then coverage, lower AURC, and lower complexity. This fallback cannot pass promotion by construction.

System transfer explains the rejection:

| Held-out RE1 system | Isotonic 90% AC@1 | Coverage |
|---|---:|---:|
| Online Boutique | 88.71% | 72.48% |
| Sock Shop | 96.56% | 60.96% |
| Train Ticket | **73.90%** | 84.80% |

For the 95% target, isotonic averaged 85.22% selective AC@1 at 50.51% coverage. Margin reached 90.70% at 56.21%, but that does not repair the preregistered 90% promotion gate and was not substituted after inspection.

## Correctness-score calibration

Held-out development diagnostics were computed only for methods that produce bounded correctness estimates:

| Method | Brier mean | Brier std | ECE mean | ECE std |
|---|---:|---:|---:|---:|
| Isotonic | 0.1566 | 0.0560 | 0.1171 | 0.0582 |
| Logistic | 0.1639 | 0.0745 | 0.1396 | 0.0851 |
| Bounded monotonic boosting | **0.1471** | 0.0510 | **0.1101** | 0.0360 |

Complete reliability-diagram bins are stored per held-out fold in `evaluation.json`. Despite reasonable aggregate calibration, no method demonstrated the required cross-system selective reliability. The deployable field is therefore still named `reliability_score`, never `probability`.

## Post-M10C locked external evaluation

This is a **post-M10C locked evaluation, not pristine external model selection**. The isotonic model and both thresholds were frozen on disjoint RE1 OOF fit/calibration partitions before these results were computed.

| Target | Frozen calibration accuracy | Calibration coverage | External coverage | External selective AC@1 | Selective MRR | Risk | AURC |
|---|---:|---:|---:|---:|---:|---:|---:|
| 90% | 90.41% | 91.25% | **95.56%** (344/360) | **81.10%** | 0.8804 | 18.90% | 0.0673 |
| 95% | 97.50% | 50.00% | 37.78% (136/360) | 98.53% | 0.9926 | 1.47% | 0.0673 |

The 95% policy is precise but misses the required meaningful coverage. The 90% policy has high coverage but fails accuracy by 8.90 percentage points.

External 90% policy by system:

| System | Cases | Accepted | Coverage | Selective AC@1 | Selective MRR | Risk | AURC |
|---|---:|---:|---:|---:|---:|---:|---:|
| Online Boutique | 120 | 116 | 96.67% | 88.79% | 0.9263 | 11.21% | 0.0395 |
| Sock Shop | 120 | 117 | 97.50% | 86.32% | 0.9193 | 13.68% | 0.0497 |
| Train Ticket | 120 | 111 | 92.50% | **67.57%** | 0.7913 | 32.43% | 0.1722 |

The complete per-suite breakdown (`RE2-OB/SS/TT`, `RE3-OB/SS/TT`) and full risk–coverage curves are in `evaluation.json`. The worst suite is RE3 Train Ticket: 57.69% selective AC@1 at 86.67% coverage.

The frozen ranker itself is unchanged: 78.89% AC@1, 94.17% AC@3, and MRR 0.8690 on 360/360 candidates. Isotonic ordering is monotone in margin, so the 10,000-resample paired comparison with margin ordering at identical 95.56% coverage is exactly zero: ΔAC@1 `0.0000`, 95% CI `[0.0000, 0.0000]`, seed `20260906`.

External isotonic diagnostic Brier is 0.1353 and ECE is 0.0345. This aggregate ECE does not validate the 90% decision threshold: the external score-0.6 bins have much lower correctness than the RE1 calibration mixture. This is why no probability claim is made.

## Independent conformal output

M10C conformal was not modified:

| Nominal | Empirical coverage | Mean set size |
|---|---:|---:|
| 90% | 91.11% | 2.683 |
| 95% | 95.00% | 3.719 |

When M10D-A abstains, the decision-support output can still return this frozen Top-K set. Reliability rejection does not invalidate or alter conformal coverage.

## Synthetic A/B/C compatibility

Result: `NOT_COMPATIBLE_WITH_FROZEN_M10C_INPUT`.

The stored synthetic A/B/C corpus uses the older 33-feature M7 representation. It does not natively contain the selected M10C metric/coverage schema or the generic metric-service candidate union. Creating missing values or label-derived mappings would violate the frozen-base and leakage rules, so no adapter was fabricated and no synthetic reliability score is claimed.

## Failure taxonomy

Counts are overlapping diagnostic tags over 76 external Top-1 ranking errors:

| Category | Count |
|---|---:|
| Ranking error | 76 |
| Confidence error: wrong and accepted | 65 |
| Candidate ambiguity: below RE1 median margin | 66 |
| Metric ambiguity: metric coverage below 0.5 | 56 |
| Missing modality | 32 |
| External domain-shift error | 76 |

Verifier contradiction misses and planner bad actions are not applicable to Track A. The dominant concrete failure is domain-dependent score/error association, especially Train Ticket, rather than candidate observability or ranker coverage.

## Performance and artifacts

In the final recorded run under three concurrent experiment tracks, frozen core plus two expert rankings took 8.43 seconds total, 23.43 ms per incident. Isotonic reliability scoring took 0.0071 seconds total, 0.0197 ms per incident. Total wall time was 261.5 seconds; these are environment-specific measurements, not optimized latency claims.

Artifacts are versioned only under `ml/models/m10d-reliability/`: preregistered protocol, frozen policy, evaluation, integrity manifest, 375-row development table, 360-row truth-free inference table, and separate 360-row labeled evaluation table. The frozen policy including OOD bounds is about 11.8 KB; no M9B/M10A/M10C artifact is overwritten.

## Decision

`RELIABILITY_V2: REJECTED`

Do not include Track A in `research/m10d-integration`. Preserve it as a reproducible negative result: cross-domain correctness calibration alone did not make Top-1 abstention transferable. Keep using frozen M10C ranking and its independent conformal prediction sets.
