# M12 — Frozen Unseen-System Shadow Validation Protocol

Status: **PRE-REGISTERED BEFORE M12 RCA SCORING**

Base commit: `c03d16f7b83ca28abfba518d574489e8c96e41ac`

Branch: `research/m12-unseen-shadow-validation`

## Objective and immutable method

M12 tests zero-shot transfer of the frozen M11 pipeline on a newly generated,
truly unseen microservice deployment. It is a validation milestone. M10C, M10D
and the five M11 Top-5 models are read-only: training, tuning, feature selection,
threshold selection and adapter changes based on labeled M12 outcomes are
forbidden.

The primary system is DeathStarBench Hotel Reservation at source commit
`6ecb09706140f8730b5385c08f1386c654c3c526`. It was selected from deployment,
licensing, telemetry and fault-injection compatibility only. Online Boutique,
Sock Shop and Train Ticket are forbidden.

## Data roles

- `M12_HEALTHY_ENGINEERING`: telemetry/unit/mapping checks and healthy baseline.
- `M12_CANARY`: mechanical injection validation only; no RCA prediction output.
- `M12_LOCKED_TEST`: truth separately sealed; predictions hidden until experiment
  configuration and freeze manifest are complete.
- After the one authorized evaluation, `M12_LOCKED_TEST -> USED_TEST` atomically
  and irreversibly.

No labeled M12 incident may modify models, features, canonical mappings, Top-K,
fault catalogue, target services, workload, or thresholds.

## Compatibility and stop gate

Proceed only if the deployment exposes at least five independently observable
services, stable workload, metadata-derived identities, defensible CPU/memory
and request/traffic signals, and reproducible service-level injection. If this
cannot be demonstrated, set `M12_UNSEEN_VALIDATION: BLOCKED`, commit the audit,
and stop without fabricating mappings.

Metrics are sampled at one second. Coarse data are never interpolated. Service
identity is a join key only. System, service, dataset, fault and root semantics
never become numeric model features.

## Engineering phases

1. Deploy the pinned system and telemetry stack.
2. Run healthy warm-up and baseline; only healthy data may fit normal-state
   statistics. Preferred durations are 5 and 15 minutes; every reduction is a
   protocol deviation.
3. Run canaries for each retained fault mechanism and inspect only injector or
   target telemetry validity evidence. Suppress RCA output.
4. Pre-register target services and a randomized 30–60 incident matrix with seed
   `20260906`, at least four services, four fault families, 15 unique clusters,
   and two repetitions for most clusters.
5. Generate truth-free telemetry and a separately sealed truth file.
6. Freeze deployment/config/code hashes, baseline, matrix, models, features,
   metrics, bootstrap and claim gates.
7. Evaluate the locked set exactly once, then make its ledger role `USED_TEST`.

Mechanical injection failure is determined independently of RCA. A failed
injection remains recorded and may have at most one replacement with the same
configuration. Poor RCA output is never an exclusion criterion.

## Frozen comparisons and metrics

Evaluate the same full valid-incident denominator with no training:

1. deterministic chance baseline;
2. generic metric maximum-shift heuristic;
3. frozen M10C compact LambdaMART;
4. frozen M10D Top-3 evidence reranker;
5. frozen M11 Top-5 evidence reranker (primary).

Report candidate coverage, AC@1/2/3/5/10, MRR, adapter failures, telemetry
completeness, inference latency and end-to-end latency. Report pooled, per-fault,
per-root, macro-fault and macro-root metrics. Missing candidates remain misses in
the denominator.

Absolute AC@K uses Wilson 95% intervals. Paired comparisons use 10,000 incident
and cluster bootstrap resamples, seed `20260906`, with cluster key
`(root_service, fault_family)`; repetitions move together.

## Pre-registered verdicts

`NEW_SYSTEM_TRANSFER` uses exactly the STRONGLY_SUPPORTED / SUPPORTED / WEAK /
NOT_SUPPORTED / BLOCKED gates from the M12 specification. A paired gain is
supported only when the relevant cluster CI lower bound is above zero.
For the pre-registered `SUPPORTED` catastrophe guard, a fault family is
catastrophic when M11 candidate coverage is below 0.90 or family AC@5 is below
0.50; the gate fails when this holds for at least half of valid fault families.

`TOP5_TRANSFER_GAIN: SUPPORTED` requires a positive cluster CI for AC@1 or MRR
and no AC@3 degradation greater than one percentage point versus M10D Top-3;
otherwise it is `NOT_SUPPORTED` (or `BLOCKED` if the experiment cannot run).

No causal, calibrated-probability, production-readiness, multi-root,
infrastructure-root, MTTR, human-productivity, memory, log, event, GNN,
Reliability-v3 or LLM claim is permitted.

## Execution audit note

The first frozen evaluation attempt raised `TypeError` before computing any
metric or verdict because the denominator assertion attempted `set(dict)`.
The original freeze and sealed-prediction hash are retained. Recovery permits
only the assertion correction, requires byte-identical predictions, and does
not allow model, adapter, data, threshold or claim-gate changes.
