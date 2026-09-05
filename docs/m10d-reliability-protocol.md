# M10D-A: cross-domain reliability v2 protocol

Status: preregistered before the post-M10C external evaluation. The M10C compact-stability ranker, its 32 selected features, and its 90%/95% conformal procedure are frozen. M10D-A may only decide whether to accept Top-1 or abstain and return the existing conformal set.

## Scope and non-leakage contract

- Frozen ranking base: M10C `dcf3fd211f10edba5808e3c26a0400ea057d405e`; branch base `b18c70c4deddb86c637a5fad4c9f68a2ff465423` adds only the required terminology correction.
- Model/method selection uses nested RE1 system holdout and never the already-inspected RE2/RE3 360 cases.
- The external run is labeled **post-M10C locked evaluation, not pristine external model selection**. No threshold, feature, hyperparameter, or acceptance gate changes are allowed after it.
- Service, system, dataset, fault, root identity, and case semantics are prohibited as reliability features. Incident ID is an opaque split/routing key only.
- M10A/M10C artifacts and results are read-only. Verifier, planner, integration, `main`, and demo code are out of scope.

## Incident representation

Inference sees only truth-free quantities: Top1–Top2 and Top1–Top3 score margins; normalized score/rank gap; inverse candidate count; metric, trace, and topology coverage; metric-family availability; Top-1 candidate observability; robust group and incident OOD fractions; metric-vs-trace expert rank agreement; frozen rank-normalized conformal-set size; ranking concentration; and modality-presence masks.

The training/evaluation table adds `top1_correct` and truth rank only after rankings and inference features exist. Deployable output explicitly removes both fields. LambdaMART scores remain arbitrary scores. Even learned correctness estimators are exposed as `reliability_score`, not as a guaranteed probability.

OOD limits are the 1st/99th training quantiles of frozen M10C features. The limits never enter ranking and are refit only on the development side of each outer fold. Mondrian regimes use only training-derived medians/quantiles of coverage, OOD, candidate count, and missing-modality state.

## Nested cross-system development

Outer held-out systems are `RE1-OB`, `RE1-SS`, and `RE1-TT`. For each outer fold, candidate/ranking predictions for the two development systems are themselves OOF: each inner system is ranked by a compact M10C model fitted on the other system. The outer ranker and metric/trace experts are trained on both inner systems and applied once to the held-out system.

OOF development incidents are deterministically split 80/20 into reliability fit and threshold calibration partitions. The held-out outer system participates in neither. This entire procedure is repeated for seeds `20260906..20260910`; reporting includes mean, standard deviation, minimum, and maximum.

Synthetic A/B/C is used only if representation-compatible. The pre-run compatibility rule is strict: the stored M8A corpus must natively contain all frozen M10C selected features and the generic metric-service candidate union. Missing fields may not be fabricated and labels may not repair mapping. Otherwise, record `NOT_COMPATIBLE_WITH_FROZEN_M10C_INPUT` and do not claim a synthetic reliability result.

## Preregistered methods

No HPO is performed. The fixed list is:

1. normalized margin threshold;
2. one-dimensional PAV isotonic calibration on Top1–Top2 margin;
3. L2-regularized logistic correctness estimator over the frozen reliability schema;
4. bounded XGBoost correctness estimator: 32 rounds, depth 2, eta 0.05, minimum child weight 8, 80% row/column sampling, monotonic directions fixed from signal semantics;
5. logistic score plus one-sided 90% Wilson lower-bound risk control;
6. logistic score plus Mondrian empirical thresholds. Groups are the Cartesian coverage/OOD/candidate-count/missing-modality regimes; groups smaller than 20 calibration cases back off to the global threshold.

For 90% and 95% policies, the ordinary threshold is the lowest score giving the largest calibration coverage at or above target accuracy. A missing feasible threshold means zero accepted incidents. Complexity tie order is the list above.

## Selection and freeze

The 90% policy promotes on development only if:

- mean outer-held-out selective AC@1 is at least 0.90;
- mean selective coverage is at least 0.50;
- every held-out system's five-seed mean selective AC@1 is at least 0.80.

Among passing methods, select maximum coverage, then accuracy, lower AURC, and lower complexity. If none pass, freeze the highest mean accuracy, then coverage, lower AURC, and lower complexity so the negative external check is still reproducible. This fallback cannot receive `PROMOTED`.

The frozen final estimator is fitted on a deterministic 80% subset of all RE1 OOF predictions; thresholds are calibrated on the disjoint 20%. Only then is it applied once to the external 360. `PROMOTED` requires both the development gate and external 90% selective AC@1 at least 0.90 with coverage at least 0.50. Otherwise verdict is exactly `REJECTED`; `INCONCLUSIVE` is reserved for an evaluation that cannot be completed.

## Metrics and uncertainty

Report selective coverage, selective AC@1, selective MRR, risk, the complete risk–coverage curve, and AURC for both target risks. For isotonic, logistic, and bounded monotonic boosting, report held-out Brier score, 10-bin ECE, and reliability-diagram data; these are diagnostics, not a probability guarantee.

The promotion comparison includes a 10,000-resample paired incident bootstrap at seed `20260906`, comparing the selected score ordering against margin-only ordering at identical coverage. Overall frozen-ranker AC@1/MRR and per-dataset external selective results remain visible.

Performance reporting includes total/per-incident frozen-ranker inference time, reliability overhead, and serialized artifact sizes. Failure analysis reports ranking, confidence, domain-shift, metric-ambiguity, missing-modality, and candidate-ambiguity counts. Verifier/planner categories are explicitly not applicable to Track A.

## Conformal isolation

M10C split-conformal construction and frozen 90%/95% results are copied by reference and are not retrained, retuned, or overwritten. On `ABSTAIN_TOP1`, decision support returns the independent conformal Top-K set. Reliability failure cannot remove or alter that output.
