# M14 Final Locked Cross-System Validation Protocol

Status: **PRE-REGISTERED; RESULTS UNOPENED**  
Base commit: `cd912c0ea561c68c6b254d73cdd88c86ecc68b95`  
Final system: OpenTelemetry Astronomy Shop at upstream commit
`8c47d47c9ac27710d2b2a153bcd53e483bffe66d`.

M14 is a one-time test of the already frozen M13 method on a new software
system. It is not a model-development milestone. The M13 five-model LambdaMART
ensemble, its 63-feature schema, `max_depth=3`, `eta=0.08`, 24 boosting rounds,
the M11 comparator and all feature formulae remain byte-for-byte frozen.

## Locked corpus

The candidate universe contains the 12 application services listed in
`deploy/m14/config.json`. Five technically independent, routinely exercised
services are injection targets: ad, cart, frontend, payment and recommendation.
The same five development fault families are used: CPU saturation, memory
pressure, network latency, packet loss and service unavailability. Every
root/fault cluster has two repetitions. The plan therefore contains exactly 50
incidents in 25 independent clusters, shuffled once with seed `20260912`.

A single deterministic mixed workload is dispatched at six operations per
second. Healthy warm-up is 300 seconds and healthy baseline collection is 900
seconds. Each incident is observed for 30 seconds followed by a five-second
cooldown. Truth is generated only from the locked injector plan. An injection
is excluded only if a prediction-independent mechanism/telemetry validity check
fails twice; no ranking is available during collection or validity checks.

## Adapters and isolation

CPU cores, working-set bytes, aggregate network bytes per second and receive
traffic bytes per second are read from the Docker Engine by the M14 exporter at
one-second cadence and mapped to the four canonical M13 metric families. Native
OTLP traces are exported to Jaeger and converted by the frozen
`m13_trace-v1` adapter. Healthy-only workload-conditioned baselines and expected
edges are fitted before incidents. Service strings are join keys only and never
learned features. The target truth file is not opened by the scoring phase.

The identical sealed incidents are ranked by deterministic chance, the generic
metric heuristic, frozen M11 and frozen M13. There is no retraining,
hyperparameter or architecture search, feature/threshold selection, reliability
tuning, or challenger model.

## Metrics and statistics

All valid incidents remain in the denominator. Report candidate coverage,
AC@1/2/3/5/10 and MRR pooled, per fault and per root, together with macro-fault,
macro-root, worst-fault and worst-root results. Absolute AC@K receives Wilson
95% intervals. M13 comparisons use 10,000 paired incident and paired-cluster
bootstrap resamples; the primary significance unit is `(root_service,
fault_family)`.

## Verdict gates

These definitions are immutable after predictions are generated:

- `STRONG_TRANSFER`: coverage >= 0.90; M13 has a positive cluster-CI gain over
  chance and over both metric heuristic and frozen M11 on AC@1 or MRR; AC@3 >=
  0.80; AC@5 >= 0.90; and fewer than half the fault families catastrophically
  collapse (coverage < 0.90 or AC@5 < 0.50).
- `SUPPORTED_TRANSFER`: coverage >= 0.90; M13 has a positive cluster-CI gain
  over chance and over either metric heuristic or frozen M11 on AC@1 or MRR;
  AC@5 >= 0.70; and fewer than half the fault families catastrophically collapse.
- `LIMITED_TRANSFER`: M13 has point-estimate MRR above chance and AC@5 >= 0.50,
  but does not satisfy the stronger baseline gates.
- `NOT_SUPPORTED`: there is no meaningful above-chance utility or candidate
  coverage structurally fails.
- `BLOCKED`: the mechanically valid locked experiment cannot be completed.

Errors are classified as `SUCCESS_AT_1`, `WITHIN_TOP3_ORDERING_ERROR`,
`WITHIN_TOP5_ORDERING_ERROR`, `ROOT_BELOW_TOP5`, `ROOT_BELOW_TOP10`, or
`CANDIDATE_UNIVERSE_MISS`. Descriptive flags are hypotheses, not causal labels.

After the result is opened, Astronomy Shop becomes `USED_TEST` and research is
frozen regardless of the verdict. No further model development is permitted.
