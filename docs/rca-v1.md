# RCA v0.1: explainable baseline algorithms

Milestone 6 adds deterministic, explainable root-cause ranking over the telemetry and anomaly evidence produced by Milestones 2–5. It is deliberately a baseline: every score is derived from explicit features, no learned model is involved, and evaluation truth is supplied only after ranking.

## Feature schema

`GET /api/features` returns schema `m6-v1`. A feature snapshot is built from one atomic anomaly-detector snapshot and the retained traces referenced by its current analysis window.

For every service it exposes:

- separate latency and error anomaly flags and Z-scores;
- bounded evidence strengths `1 - exp(-z / threshold)` for positive Z-scores;
- the primary signal (`error`, then `latency`, otherwise `none`);
- the M5 service severity retained for the `max_severity` baseline;
- topology membership, affected and observed-set membership, precision, recall, and F1;
- trace-local latency evidence, including the selected operation and coverage.

Evidence strength is a monotonic normalization for comparing signals. It is not a probability or calibrated confidence.

The diagnostic sets are:

- `U`: services with enough current samples for at least one operation;
- `O`: anomalous services in `U` for the selected primary signal;
- `C`: root-cause candidates, equal to `O` in v0.1;
- `P(c)`: the predicted affected set for candidate `c`, intersected with `U`.

The snapshot state is explicit: `baseline_not_frozen`, `insufficient_current_data`, `no_anomaly`, or `ready`. Rankings are emitted only in `ready` state.

## Active incident topology

The preferred graph is reconstructed only from the exact retained traces named by the current M5 sample references. A current sample is covered when its referenced SERVER span is still present. The response exposes:

- `topology_source`: `active_traces` or `global_fallback`;
- `active_topology_trace_coverage`: covered current samples divided by all current samples.

The threshold is configured by `MIN_ACTIVE_TOPOLOGY_COVERAGE` and defaults to `0.7`. If coverage reaches it, only cross-service parent-child edges in those active traces are used. This prevents an old retained branch from changing the incident graph. If coverage is too low, the choice is explicit and deterministic: the algorithm uses the aggregated M4 graph and reports `global_fallback` rather than silently mixing sources.

For candidate `c`, reverse reachability finds `c` and all transitive callers. The implementation is cycle-safe. After intersecting with `U`, topology consistency is the F1 score between `P(c)` and `O`.

Examples for `Gateway -> Orders -> Payment`:

- Payment anomaly: `P(Payment) = {Gateway, Orders, Payment}`;
- Orders anomaly: `P(Orders) = {Gateway, Orders}`;
- Gateway anomaly: `P(Gateway) = {Gateway}`.

## Trace-local latency evidence

For every referenced SERVER span, observed downstream wait is the union of intervals of all same-service CLIENT descendants, clipped to the SERVER interval. Interval union prevents overlapping calls from being counted twice.

`exclusive_observed_duration = server_duration - union(downstream_wait_intervals)`

The exclusive ratio is clamped to `[0,1]`. Missing or malformed traces reduce trace coverage rather than inventing evidence. This quantity is an observation from instrumented client spans; it is not CPU time and does not account for uninstrumented work or asynchronous activity.

For a latency anomaly, local evidence is:

`operation_strength * median_exclusive_ratio * trace_coverage`

The service operation with maximum value is selected deterministically. For an error anomaly, local evidence is the bounded error strength because an error span already identifies the failing service boundary.

## Rankers

`GET /api/rca` returns four deterministic rankings:

| Algorithm | Score |
|---|---|
| `max_severity` | M5 service severity |
| `topology_consistency` | topology F1, then primary strength |
| `local_evidence` | trace-local evidence |
| `hybrid_v1` | topology F1 multiplied by local evidence |

Final ties use the service name, so repeated reads over unchanged evidence are byte-stable. Each ranked candidate includes machine-readable topology and local-evidence components. The API never accepts or exposes ground truth.

## Offline evaluation

`internal/evaluation` evaluates an already-produced ranking against an externally supplied expected service. It reports rank, AC@1, AC@3, and reciprocal rank. Truth is not passed to feature extraction or any ranker, which prevents evaluation leakage.

## Limitations

RCA v0.1 intentionally has the following boundaries:

1. It ranks only services already marked anomalous by M5; it does not discover a quiet root cause behind a noisy caller.
2. The graph represents observed synchronous cross-service calls, not every architectural dependency.
3. Low active-trace coverage falls back to the longer-lived global graph, which may contain historical branches.
4. The retained-sample join depends on trace retention and correct trace/span identifiers.
5. Exclusive observed duration is not CPU time and can include queueing, runtime pauses, locks, and uninstrumented downstream work.
6. Error-first primary-signal selection is a fixed heuristic.
7. Threshold-normalized strengths are not probabilities or calibrated confidence values.
8. Small windows and median aggregation deliberately trade sensitivity for robustness.
9. Candidate ties are resolved lexicographically, not by additional causal evidence.
10. There is no ML, GNN, causal discovery, RCAEval adapter, or dataset-generation pipeline in Milestone 6.
