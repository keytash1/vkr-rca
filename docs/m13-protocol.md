# M13 — Cross-Domain Diagnostic Generalization Protocol

Status: **PRE-REGISTERED BEFORE M13 MODEL SCORING**

Base commit: `7edff6b5fd874ddac47f8433425fef15089df5b5`

Branch: `research/m13-cross-domain-generalization`

## Objective and isolation

M13 develops a service-invariant diagnostic ranker that combines direct metric
anomaly, canonical trace-local evidence, propagation, expected-signal
disappearance and explicit modality coverage. The benchmark identity, service
name, operation vocabulary, route, root label and fault label are forbidden
learned inputs.

M12 Hotel Reservation has the irreversible role `USED_TEST_READONLY`. Its 50
incident IDs, labels, telemetry and scores are forbidden for M13 fitting,
feature selection, architecture selection, fusion, Top-K selection and
calibration. M12 motivates the hypotheses only. OpenTelemetry Astronomy Shop is
reserved for a later final locked test and is not deployed or scored in M13.

## Development corpus

The selected `NEW_DEVELOPMENT` system is DeathStarBench Social Network at
commit `6ecb09706140f8730b5385c08f1386c654c3c526`. The planned corpus has six root
services, five fault families, two workload regimes and two repetitions:
`6 × 5 × 2 × 2 = 120` incidents and 60 repetition-isolated clusters. Execution
order is shuffled with seed `20260906`. Ground truth comes only from injector
configuration.

Healthy warm-up is at least 120 seconds and baseline at least 600 seconds. The
preferred 300/900 durations remain the target if the 2 CPU/8 GiB ARM64 host can
sustain the emulated upstream application. Healthy data alone fit metric, span
rate, activity, edge-presence and workload-conditioned baselines.

Each incident window lasts 15 seconds. Both regimes use the upstream-style
mixed workload (60% home-timeline reads, 30% user-timeline reads and 10%
compose-post); their fixed dispatch rates are 6 and 9 requests/second.

Pre-scoring amendment (2026-09-12): the originally planned high rate of 18 RPS
was rejected by the healthy gate after 599/5400 requests timed out during the
five-minute segment on the 2 CPU ARM64 host. A subsequent 12 RPS stress attempt
also left the emulated stack unresponsive, so 9 RPS is the final amended high
regime. It must pass a 60-second stress-smoke and the complete accepted baseline
without transport or server failures. No model was fit or scored before these
amendments.

## Frozen development protocols

All repetitions stay within cluster
`(system, root_service, fault_family, workload_regime, intensity)`. The primary
new-system development estimate uses deterministic five-fold grouped OOF.
Complementary diagnostics hold out root services and fault families. Existing
RE1 development systems may participate only through compatible identity-free
features with unavailable M13 modalities explicitly masked.

The primary metric heuristic is deterministic maximum robust metric shift and
is never weakened. Serious models are:

1. chance;
2. generic metric heuristic;
3. frozen M11;
4. extended shallow evidence ranker;
5. two-expert ranker with OOF-only fusion;
6. full-candidate challenger only when Top-5 membership is an observed
   development bottleneck.

The fixed search is `max_depth ∈ {2,3}`, `eta ∈ {0.03,0.08}` and
`rounds ∈ {24,48}`. Seeds are `20260906..20260910`. Grouped ranking uses
`rank:ndcg`. Fusion training receives only out-of-fold expert predictions and
generic coverage, disagreement, margin, OOD and candidate-count signals.

## Pre-registered hypotheses

- H1: metrics plus trace/propagation beats metrics-only on AC@1 or MRR.
- H2: expected disappearance improves service-unavailable clusters over the
  identical architecture without disappearance.
- H3: the selected challenger beats the metric heuristic on pooled development
  OOF AC@1 or MRR.
- H4: network/unavailability improves without more than five AC@1 points of
  CPU/memory regression.
- H5: full-candidate ranking recovers roots below Top-5 without more than one
  AC@3 point of degradation.

Matched ablations are metrics-only, traces-only, metrics+traces,
metrics+disappearance, metrics+propagation, metrics+traces+propagation, full
diagnostic evidence, and full evidence with/without ranking context. Permutation
importance uses the same OOF predictions and feature groups.

## Statistics and promotion

Absolute AC@K uses Wilson 95% intervals. Paired comparisons use 10,000 incident
and 10,000 cluster bootstrap resamples with seed `20260906`; cluster intervals
are the claim gate. M13 is promoted only if every guardrail in the supplied M13
specification holds, including statistically supported gains over chance,
metric heuristic and frozen M11, AC@3/5 preservation, fault-family guardrails,
material service-unavailable improvement and no network MRR regression.

Trace and disappearance claims require matched ablations, not tree gain.
A GNN is implemented only if trace incremental value is supported and remaining
errors show a propagation bottleneck. Reliability V3 is considered only after
the ranker is frozen and uses OOF predictions with nested grouped validation.

No result from the reserved final system is produced in M13.
