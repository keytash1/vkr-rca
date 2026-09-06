# M11 — Generalization & Error-Driven Hardening Protocol

Status: **PRE-REGISTERED BEFORE M11 MODEL SCORING**

Base commit: `2fd38885ef8c0f0930d1830d8fd429fb6594f8a4`

Branch: `research/m11-generalization-hardening`

## Objective

M11 tests whether the frozen M10D Evidence-Aware Top-3 Reranker should remain the
research champion or whether a bounded candidate-recovery extension is supported.
It is an error-analysis and generalization milestone, not an unconstrained score
search. M10A, M10C, M10D, RE2 and RE3 remain immutable.

## Frozen reference

The M10D external benchmark is frozen at AC@1 `0.8361111111`, AC@2
`0.9305555556`, AC@3 `0.9416666667`, and MRR `0.8977211099`. Exact artifact and
schema hashes are recorded in `ml/models/m11/preflight.json`.

## Data roles and isolation

Roles are machine-readable in `ml/models/m11/data-ledger.json`.

- RE1-OB, RE1-SS and RE1-TT: `DEVELOPMENT_EXISTING`; system-held-out OOF only.
- Synthetic A/B/C: `DEVELOPMENT_AUXILIARY`; diagnostics only, no promotion vote.
- RE2 and RE3: `USED_TEST_READONLY`; historical post-freeze regression only.
- Public datasets: audited for compatibility before any M11 model score. A new
  dataset receives `NEW_DEVELOPMENT` or `LOCKED_NEW_TEST` only after an adapter,
  service-level truth contract and integrity seal pass without inspecting locked
  labels for model selection.

Training, feature selection, calibration and model selection reject every incident
ID assigned `USED_TEST_READONLY`, `USED_TEST`, or `LOCKED_NEW_TEST`. A locked test can
transition once, atomically, to `USED_TEST`; it can never transition back.

## Pre-registered candidate-recovery study

The only model comparison is M10D Top-3 against Top-K candidates for K in
`{3, 5, 10}`. Every variant uses the same 13 truth-free evidence features, the
same five seeds (`20260906`…`20260910`), the same shallow XGBoost recipe and the
same RE1 system-held-out folds. K=3 is the numerical control. No RE2/RE3 outcome
may affect this choice.

Promotion requires all of:

1. cluster-bootstrap 95% CI lower bound above zero for AC@1 or MRR versus Top-3;
2. AC@3 loss no worse than 1 percentage point;
3. no held-out RE1 system loses more than 5 percentage points AC@1;
4. candidate-universe coverage does not decrease.

If no challenger passes, the verdict is `KEEP_M10D_TOP3`.

## Metrics and uncertainty

Report candidate-universe coverage, truth-rank histogram, AC@1/2/3/5/10, MRR,
and the oracle maximum AC@1 for K=1/2/3/5/10. Denominators always include every
incident; an unobservable root is a miss. Error decomposition separates
unobservable roots, roots below K, and within-K ordering failures.

Paired cluster bootstrap uses 10,000 resamples, seed `20260906`, and clusters by
`(system, root_service, fault_type)`. Incident-level positive evidence whose
cluster interval crosses zero is labelled `WEAK_CLUSTER_NOT_SUPPORTED`.

## New-data, trace, graph and reliability gates

Public data are chosen by compatibility only, never by model score. No service
alias, filename, directory name, fault label or ground truth may enter inference
features. Adapters emit truth-free telemetry and candidate identity; truth is
joined from a separately sealed source only for evaluation.

A trace/topology incremental study runs only when `NEW_DEVELOPMENT` contains a
meaningful number of trace-bearing incidents and supports matched-modality
ablations. A GNN is considered only after a positive graph/modal signal and a
demonstrated bottleneck of handcrafted topology features. Reliability v3 requires
an independent new domain. Otherwise the mandatory verdicts are respectively
`INCONCLUSIVE`, `NOT_JUSTIFIED`, and `BLOCKED`.

## Freeze and evaluation order

1. Freeze this protocol, data ledger and preflight hashes.
2. Audit public datasets and assign no role unless compatibility is established.
3. Run RE1 OOF error decomposition and candidate recovery.
4. Write `freeze-manifest.json` with the selected architecture.
5. Only then run descriptive historical RE2/RE3 regression.
6. A newly compatible locked test, if any, is opened once after freeze and its
   ledger role is irreversibly changed to `USED_TEST`.

M11 makes no memory, log, event or LLM claims.
