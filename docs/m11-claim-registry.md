# M11 Claim Registry

## Candidate recovery and ranking evidence

- CLAIM: Expanding the evidence-aware reranker from Top-3 to Top-5 improves ranking.
- HYPOTHESIS: AC@1 or MRR has a positive pre-registered cluster CI with no guardrail failure.
- STATUS: SUPPORTED.
- DATASET: RCAEval RE1-OB/SS/TT.
- DATA ROLE: DEVELOPMENT_EXISTING.
- PROTOCOL: system-group OOF, same 13 features, shallow XGBoost, five fixed seeds.
- DENOMINATOR: 375 incidents.
- BASELINE: frozen M10D Top-3 OOF control.
- METRIC: AC@1 and MRR.
- RESULT: AC@1 0.7947; MRR 0.8775; decision PROMOTE_TOP5.
- INCIDENT CI: AC@1 [0.0027, 0.0267]; MRR [0.0044, 0.0207].
- CLUSTER CI: AC@1 [0.0027, 0.0267]; MRR [0.0028, 0.0235].
- LIMITATION: The method only reorders existing candidates; it does not discover missing services.

## Candidate discovery

- CLAIM: M11 improves candidate-universe discovery.
- HYPOTHESIS: The true root enters a candidate universe where it was previously absent.
- STATUS: INCONCLUSIVE.
- DATASET: RCAEval RE1.
- DATA ROLE: DEVELOPMENT_EXISTING.
- PROTOCOL: candidate universe held fixed; only initial Top-K membership changes.
- DENOMINATOR: 375 incidents.
- BASELINE: M10C candidate universe.
- METRIC: candidate-universe coverage.
- RESULT: not tested; the universe was held fixed and coverage remained 1.0000.
- INCIDENT CI: not applicable.
- CLUSTER CI: not applicable.
- LIMITATION: candidate generation was outside M11 scope.

## Historical regression

- CLAIM: The frozen M10D result remains reproducible and the selected M11 architecture does not regress it descriptively.
- HYPOTHESIS: Frozen metrics reproduce exactly; selected architecture is reported without affecting selection.
- STATUS: SUPPORTED_WITH_QUALIFICATION.
- DATASET: RCAEval RE2/RE3.
- DATA ROLE: USED_TEST_READONLY.
- PROTOCOL: opened after freeze; no selection or tuning.
- DENOMINATOR: 360 incidents.
- BASELINE: M10D Top-3 AC@1 0.8361, MRR 0.8977.
- METRIC: AC@1/2/3/5/10 and MRR.
- RESULT: exact baseline reproduced; selected Top-5 AC@1 0.8417, MRR 0.9039.
- INCIDENT CI: AC@1 [-0.0056, 0.0167]; MRR [-0.0006, 0.0140].
- CLUSTER CI: AC@1 [-0.0055, 0.0168]; MRR [-0.0003, 0.0139].
- LIMITATION: known historical test; not new-system evidence.

## Trace contribution

- CLAIM: traces/topology add transferable incremental value.
- HYPOTHESIS: matched-modality NEW_DEVELOPMENT ablations have a positive cluster CI.
- STATUS: BLOCKED.
- DATASET: none compatible.
- DATA ROLE: NEW_DEVELOPMENT unavailable.
- PROTOCOL: matched incident/candidate/fold ablation was gated off.
- DENOMINATOR: 0 new-domain incidents.
- BASELINE: metrics-only reranker.
- METRIC: AC@1 and MRR.
- RESULT: no experiment executed.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: no validated trace-bearing new development corpus.

## New-system transfer

- CLAIM: M11 transfers to genuinely new public systems.
- HYPOTHESIS: selected challenger beats M10D on a one-time locked new-domain test.
- STATUS: BLOCKED.
- DATASET: none selected.
- DATA ROLE: NEW_DEVELOPMENT and LOCKED_NEW_TEST unavailable.
- PROTOCOL: compatibility audit before scoring.
- DENOMINATOR: 0.
- BASELINE: M10D.
- METRIC: candidate coverage, AC@1/2/3/5/10, MRR.
- RESULT: no locked evaluation.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: audited sources need non-fabricated service-level adapters.

## Reliability and autonomous detection

- CLAIM: Reliability v3 or autonomous detection is validated.
- HYPOTHESIS: an independent development domain supports nested-holdout reliability targets.
- STATUS: BLOCKED.
- DATASET: none compatible.
- DATA ROLE: NEW_DEVELOPMENT unavailable.
- PROTOCOL: conditional gate; RE2/RE3 forbidden for threshold selection.
- DENOMINATOR: 0.
- BASELINE: rejected M10D Reliability v2.
- METRIC: AURC, selective AC@1, coverage, conformal coverage/set size.
- RESULT: not run; no autonomous-detection claim.
- INCIDENT CI: not available.
- CLUSTER CI: not available.
- LIMITATION: no independent labeled domain.

Cluster rule: a positive incident-level delta with a cluster-bootstrap interval
crossing zero is `WEAK_CLUSTER_NOT_SUPPORTED`, not a supported claim.

Forbidden claims: causal verification, calibrated probability, exhaustive root
cause discovery, production readiness, or memory/log/event/LLM generalization.
