# Thesis claim registry

This registry is the allowed wording for the final thesis. Every claim states its protocol, denominator, result, and limitation.

## Claim 1

- **CLAIM:** Metric evidence substantially improves localization over trace-only evidence.
- **HYPOTHESIS:** Metric LambdaMART has higher incident-level AC@1 and MRR than trace-only soft_hybrid_v1.
- **STATUS:** SUPPORTED.
- **DATASET:** RE2-OB, RE2-TT, RE3-OB, and RE3-TT.
- **PROTOCOL:** Frozen M9B metric model and unchanged trace baseline rank identical incidents.
- **DENOMINATOR:** 216 externally triggered, root-observable cases.
- **BASELINE:** Unchanged M7 soft_hybrid_v1 trace ranking.
- **METRIC:** AC@1 and MRR.
- **RESULT:** Metric AC@1 80.1% vs trace 30.6%.
- **95% CI:** Paired ΔAC@1 +0.495 [+0.407, +0.579]; ΔMRR +0.414 [+0.353, +0.475].
- **LIMITATION:** This supports the metric-evidence claim, not a claim that traces alone caused the full improvement.

## Claim 2

- **CLAIM:** Full multimodal fusion improves metrics-only under matched cross-system training.
- **HYPOTHESIS:** All-modality LambdaMART has higher AC@1 and MRR than metrics-only under the same folds and training recipe.
- **STATUS:** PARTIALLY SUPPORTED / METRIC-DEPENDENT.
- **DATASET:** RE2-OB, RE2-TT, RE3-OB, and RE3-TT.
- **PROTOCOL:** Frozen RE2 cross-system folds; identical candidates, parameters, rounds, and rows.
- **DENOMINATOR:** 216 matched externally triggered, root-observable cases; per-suite results are also reported.
- **BASELINE:** Metrics-only LambdaMART retrained under the frozen all-modality protocol.
- **METRIC:** AC@1 and MRR.
- **RESULT:** All-modality AC@1 70.4% vs metrics-only 64.4%.
- **95% CI:** Paired ΔAC@1 +0.060 [+0.000, +0.120]; ΔMRR +0.038 [+0.005, +0.072].
- **LIMITATION:** The AC@1 CI touches zero, so its gain is not statistically stable; MRR is supported. The aggregate gain is driven by RE2-TT, and RE3-OB has only six descriptive incidents.

## Claim 3

- **CLAIM:** The service-invariant representation transfers across systems.
- **HYPOTHESIS:** Identity-free metric and multimodal rankers retain useful accuracy on held-out systems.
- **STATUS:** SUPPORTED WITH COVERAGE QUALIFICATION.
- **DATASET:** Synthetic RE1 plus external RE2/RE3 suites.
- **PROTOCOL:** RE1 system holdouts and frozen external evaluation with service/system/case/root/fault identity forbidden.
- **DENOMINATOR:** RE1 fold-specific held-out cases; 336 observable and 360 full-denominator external metric cases.
- **BASELINE:** No single competing baseline; the test is performance under held-out-system and external transfer.
- **METRIC:** AC@1 and MRR per fold, conditional external, and full external denominator.
- **RESULT:** RE1 held-out AC@1 is 51.2%, 93.6%, and 78.9%; conditional external AC@1 is 81.8%.
- **95% CI:** Seed-robustness CIs are reported in docs/m10a-results.md; no single pooled transfer-delta CI applies.
- **LIMITATION:** Full-denominator external AC@1 is 76.4%; RE3-OB root observability is 6/30.

## Claim 4

- **CLAIM:** Learning-to-Rank outperforms the simple metric heuristic.
- **HYPOTHESIS:** Metric LambdaMART has higher AC@1 and MRR than metric_max_shift on matched cases.
- **STATUS:** SUPPORTED.
- **DATASET:** All RE2/RE3 metric suites.
- **PROTOCOL:** Frozen RE1-trained metric LambdaMART versus deterministic metric_max_shift.
- **DENOMINATOR:** 336 identical root-observable external cases.
- **BASELINE:** metric_max_shift heuristic.
- **METRIC:** AC@1 and MRR.
- **RESULT:** Learned AC@1 81.8% vs heuristic 50.6%.
- **95% CI:** Paired ΔAC@1 +0.312 [+0.259, +0.366]; ΔMRR +0.260 [+0.220, +0.299].
- **LIMITATION:** The learned score is not a calibrated probability.

## Claim 5

- **CLAIM:** Adding metrics improves observable code-fault localization.
- **HYPOTHESIS:** Metric LambdaMART has higher AC@1 and MRR than trace-only ranking on RE3 code faults.
- **STATUS:** SUPPORTED WITH COVERAGE QUALIFICATION.
- **DATASET:** RE3-OB and RE3-TT.
- **PROTOCOL:** Frozen metric LambdaMART versus unchanged soft_hybrid_v1 on identical observable incidents.
- **DENOMINATOR:** 36 root-observable code-fault cases.
- **BASELINE:** Unchanged M7 soft_hybrid_v1 trace ranking.
- **METRIC:** AC@1 and MRR.
- **RESULT:** Metric AC@1 77.8% vs trace 0.0%.
- **95% CI:** Paired ΔAC@1 +0.778 [+0.639, +0.917]; ΔMRR +0.661 [+0.549, +0.760].
- **LIMITATION:** Only 6/30 RE3-OB roots are observable; the result does not cover all RE3-OB incidents.

## Claim 6

- **CLAIM:** Hard anomaly gating limits autonomous end-to-end RCA.
- **HYPOTHESIS:** Autonomous M5-gated end-to-end accuracy is materially lower than externally triggered localization.
- **STATUS:** SUPPORTED AS A DESCRIPTIVE SYSTEM RESULT.
- **DATASET:** RCAEval RE2/RE3 trace-capable suites.
- **PROTOCOL:** Frozen M5/v1 detector followed by RCA, shown alongside externally triggered M9B localization.
- **DENOMINATOR:** Autonomous detection/end-to-end: 240 cases; triggered metric comparison: 216 observable cases.
- **BASELINE:** Externally triggered M9B metric LambdaMART is the reference mode.
- **METRIC:** Detection recall, healthy FPR, end-to-end AC@1, and triggered conditional AC@1.
- **RESULT:** M5 recall 52.9%, autonomous AC@1 34.6%, triggered AC@1 80.1%.
- **95% CI:** Not applicable: denominators and conditioning differ, so no paired effect CI is claimed.
- **LIMITATION:** This is a descriptive system comparison, not a paired causal estimate.

## Claim 7

- **CLAIM:** Trace-only temporal CUSUM transfers across domains.
- **HYPOTHESIS:** Synthetic-selected detector-v2 improves external recall while satisfying the preregistered healthy-FPR gate.
- **STATUS:** REJECTED.
- **DATASET:** Synthetic A/B/C validation followed by 240 RCAEval incidents and 240 paired controls.
- **PROTOCOL:** Detector-v2 was selected on synthetic data and frozen before external evaluation.
- **DENOMINATOR:** 240 external fault cases and 240 paired pseudo-healthy controls.
- **BASELINE:** Frozen M5/v1 detector plus the preregistered external acceptance gate.
- **METRIC:** Detection recall and healthy false-positive rate.
- **RESULT:** External recall reached 99.6%, but healthy FPR also reached 99.6%; verdict NOT_JUSTIFIED.
- **95% CI:** M9A paired recall-difference CI [0.404, 0.529]; FPR-difference CI [0.887, 0.958].
- **LIMITATION:** Sequence-length and domain calibration failed; detector-v2 is excluded from the final method.
