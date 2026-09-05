# M10C protocol: Coverage-Aware Multi-Source Learning-to-Rank RCA v2

Status: pre-registered before M10C test evaluation. M10A and M10B remain immutable.

## Research question

Can a compact, modality-aware learning-to-rank system improve robustness and
observability over the frozen M10A metric LambdaMART without hiding failures
behind a conditional denominator?

The method has five separately testable stages:

1. Candidate Generation: the union of service entities found in metrics and
   traces. A metric-only service remains eligible when traces are absent or do
   not name it. Infrastructure entities are not silently promoted to service
   candidates.
2. Diagnostic Representation: canonical metric families plus retained trace,
   topology, coverage, incident-relative percentile, exclusive-duration and
   downstream-wait evidence. The schema is `m10c-v2-candidate`.
3. Modality Experts: metric-only LambdaMART and trace/topology LambdaMART.
4. Rank Fusion: early fusion, mean rank-percentile fusion, reciprocal-rank
   fusion, and a stacked LambdaMART meta-ranker trained only on out-of-fold
   expert predictions.
5. Reliability: OOD is reported but never used for ranking; split-conformal
   rank sets and a calibrated `TOP1`/`ABSTAIN_TOP1` policy are evaluated on
   partitions disjoint from fitting and calibration.

## Locked data roles

- Training/tuning: RE1 system holdouts and the training side of each RE2
  cross-system fold.
- Calibration: deterministic incident-hash subsets removed from training.
- Final external tests: RE2/RE3 target systems, never used for feature,
  fusion, conformal, or abstention selection.
- Full denominator: all 360 RE2/RE3 external cases. An absent root is rank 0.
- Labels are joined only after truth-free telemetry artifacts are sealed.

All transformations that learn parameters (feature selection, workload
regression, robust median/IQR, fusion and reliability thresholds) are fitted
on training or calibration data only.

## Candidate and coverage metrics

Report Root Observable Coverage, Candidate Recall and mean candidate count by
RE1, RE2, RE3, each system and all 360 external cases. The frozen reference is
336/360 root-observable cases. The 24 missing cases receive an A-G audit before
any adapter change: absent telemetry, rejected mapping, trace-only root,
infrastructure/database, granularity mismatch, naming mismatch, or other.

## Feature selection

Selection is group-first over cpu, latency, memory, disk, network/socket,
workload, trace, topology and coverage. For every training fold and fixed seed,
record use frequency, normalized total gain and label-safe permutation
importance. A non-structural feature is eligible only when it is used in at
least 60% of relevant models and has positive permutation contribution in at
least 60% of folds. Availability, coverage and topology masks may be retained
by pre-declared structural exception. Target: at least 50% reduction from the
253-column M9B schema, preferably 40-100 columns.

The compact gate is AC@1 no worse than -1.5 percentage points and MRR no worse
than -0.015 on training-side validation. Workload-conditioned residuals are
accepted only if held-out transfer improves or false workload evidence falls.

## Fusion selection

Choose one fusion method on training/system-validation results using MRR first,
AC@1 second, and lower complexity on a tie. The final external partition cannot
select a method. Missing-modality masks, relative scores, rank percentiles,
coverage, expert disagreement and graph context are allowed; raw service names
and labels are forbidden.

## Stress and reliability

Run label-blind masking with complete metrics, traces or topology removed;
30%/50% trace-span loss; one and multiple metric-family losses; and a metric
candidate absent from traces. Report overall AC@1/2/3 and MRR under every
condition.

OOD uses training medians/IQR and quantile fences and is diagnostic only.
Split-conformal 90% and 95% rank sets use rank normalized by candidate count;
only marginal empirical coverage is claimed. Abstention thresholds use margin,
expert disagreement, coverage, observability and OOD, are selected on
calibration for maximum coverage at at least 90% Top-1 accuracy (also reported
at 95%), and are frozen before test. Report coverage, selective AC@1/MRR, risk,
risk-coverage curves and AURC alongside unselective metrics.

## Promotion gates

The final verdict is exactly `PROMOTE_CORE_V2` or
`KEEP_FROZEN_M10A_CORE`. Minimum gates:

- full-denominator AC@1 decline no greater than 1 percentage point;
- MRR decline no greater than 0.01;
- root-observable coverage not lower than 336/360;
- at least 50% feature reduction or an objectively demonstrated robustness gain;
- selective Top-1 accuracy at least 90% at meaningful coverage;
- held-out conformal empirical coverage reaches both nominal levels within
  finite-sample tolerance;
- graceful degradation under pre-registered missingness.

A strong promotion additionally needs either +3 points full AC@1, or matched
AC@1 plus no more than half the features, greater root coverage, at least 60%
coverage at 90% selective Top-1, and a 90% conformal average set size no larger
than three. Failure of a required gate keeps M10A as the production thesis core.

## Reproducibility and exclusions

Fixed seed: `20260905`. Algorithms are bounded and CPU-friendly. No GNN,
causal discovery or LLM judge is introduced. Logs and events remain an audited
future-work modality. M10C writes only `m10c-*` artifacts and never mutates the
M9B models, M10A freeze, M10B demo or thesis claims.

