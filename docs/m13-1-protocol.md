# M13.1 — Nested Methodological Hardening Protocol

Status: **PRE-REGISTERED BEFORE NESTED SCORING**

Base commit: `2c295760bff8b644cee8f2c0d460bbf98cf71735`

Branch: `research/m13-1-nested-validation`

## Objective

M13.1 estimates the complete M13 model/configuration selection procedure without
allowing an outer-test repetition cluster to influence hyperparameter or
architecture selection. It is a methodological audit of the frozen M13
development procedure, not a new model-development milestone.

No feature, modality, candidate universe, fault catalogue, baseline formula,
trace adapter, propagation rule, disappearance rule, model family or
hyperparameter value may be added or changed in response to M13.1 results.

## Frozen inputs

The sole dataset is the existing 120-incident, 60-cluster DeathStarBench Social
Network `NEW_DEVELOPMENT` corpus. Its ground truth and telemetry seals remain
those of M13. `USED_TEST_READONLY` RE2/RE3, M12 Hotel Reservation, and the
`RESERVED_FINAL_TEST` OpenTelemetry Astronomy Shop are forbidden inputs.

The frozen architecture candidates are:

1. extended evidence reranking restricted to frozen M11 Top-5 membership;
2. two-expert Top-5 fusion with fusion training on expert OOF predictions only;
3. full-candidate diagnostic reranking.

All use the frozen M13 feature representation. The fixed grid is
`max_depth ∈ {2,3}`, `eta ∈ {0.03,0.08}`, `rounds ∈ {24,48}`.

## Nested protocol

The outer protocol has five deterministic grouped folds. Its unit is the full
cluster `(system, root_service, fault_family, workload_regime, intensity)`; both
repetitions always remain together. Each outer fold contains 12 clusters and 24
incidents.

For each outer fold:

1. remove the complete outer-test fold;
2. run four-fold grouped inner OOF only on the 48 outer-train clusters;
3. select the M13 hyperparameter configuration using full-representation inner
   OOF MRR, followed by AC@1 and the frozen deterministic tie-break;
4. evaluate all three frozen architecture candidates using that selected
   configuration and inner OOF predictions only;
5. select the architecture using inner OOF MRR, followed by AC@1 and name;
6. fit the selected procedure on all outer-train incidents;
7. score the untouched outer-test incidents exactly once.

For two-expert fusion, every fusion-training score is itself produced out of
fold inside the applicable training partition. In-sample expert predictions are
forbidden.

Aggregate only the five untouched outer-test prediction sets. Compare them with
chance, the generic metric heuristic and frozen M11 on the identical full
denominator. Report AC@1/2/3/5/10, MRR, Wilson intervals, 10,000 paired incident
bootstrap samples, 10,000 paired cluster bootstrap samples, per-fault,
per-root, worst groups and fold-level selection stability. Bootstrap seed is
`20260906`; the cluster interval is the significance gate.

## Decision rule

`FINAL_TEST_READY = YES` only if the nested procedure beats both the generic
metric heuristic and frozen M11 on AC@1 or MRR with a positive 95% cluster
bootstrap lower bound, preserves full candidate coverage, uses the complete
denominator, and passes every isolation/provenance check.

Otherwise `FINAL_TEST_READY = NO`. No silent retuning is allowed.

M13.1 does not replace or edit the frozen M13 runtime. Regardless of the result,
Astronomy Shop remains untouched for later human-approved one-time evaluation.
