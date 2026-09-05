# M10C external stress compatibility protocol

This document is a label-blind compatibility decision, not an accuracy result.

## TORAI

TORAI is treated as a modern multi-source/blind-spot baseline within RCAEval,
not as an independent external dataset. The official RCAEval repository lists
TORAI among its baselines; its processed data are 270 RE2 cases published on a
separate Figshare record. Reproduction must pin the upstream revision, dataset
hash, Python 3.8 environment, runtime, command and result. Upstream files remain
untouched. Comparison uses identical incident IDs and service-level targets or
is marked non-comparable.

Audit result: the local official RCAEval checkout is pinned at
`405c8fd24071af41ceb4b3aabb451e5e3e15d6c6`. The TORAI implementation SHA-256
is `549b75a43c39b7f2f148b4de0e864892ec8294fca09eebf5783ba48f6ceeec5f` and
its dependency lock SHA-256 is
`0345a13eaf3f82901c6b416d42c29ad6122997510a7d09d7abee30249d9f1aeb`.
The required Figshare corpus and Python 3.8 runtime are not present locally.
The official documentation reports fault-wise Avg@5 examples rather than the
locked service-level AC@1/MRR denominator. Runtime result is therefore
`NOT_RUN_INCOMPARABLE_ENVIRONMENT`, not an invented baseline number. TORAI
remains a design/baseline comparison only.

## Cloud-OpsBench

Cloud-OpsBench is considered only after the M10C core is frozen. Its present
task is agentic Kubernetes troubleshooting over state snapshots and tool
evidence, with 754 cases and 57 fault types; this differs from RCAEval's
telemetry time-series service ranking.

Before reading diagnoses or labels, the adapter audit must record:

- whether a case has time-aligned numeric metric series;
- whether a service-level candidate universe is recoverable;
- whether a single service root is defined at compatible granularity;
- which canonical M10C metric families can be mapped without case-specific
  rules;
- whether timestamps support the pre/post incident windows;
- immutable source revision and hashes.

The compatible subset is pre-registered from this ontology only. Labels may be
opened after that subset is sealed, and no model, feature, threshold or mapping
may be tuned on Cloud-OpsBench outcomes. If the mapping is not defensible, M10C
publishes only this compatibility report and makes no accuracy claim.

Audit result: current Cloud-OpsBench is an agentic interactive troubleshooting
benchmark with Kubernetes state/tool caches and natural-language diagnoses,
not a time-aligned service-ranking corpus. Its 754 cases and 57 fault types are
valuable for a future planner evaluation, but there is no defensible automatic
mapping to the locked M10C candidate/incident windows. Status is
`COMPATIBILITY_ONLY`; no labels were used for model tuning and no accuracy
result is reported. Since M10C did not replace the frozen core, the protocol's
"only after core freeze" condition also prevents a post-hoc external run.


Official sources checked during protocol preparation:

- RCAEval repository and baseline/data instructions: <https://github.com/phamquiluan/RCAEval>
- TORAI processed RE2 data: <https://doi.org/10.6084/m9.figshare.31925976>
- Cloud-OpsBench repository: <https://github.com/LLM4Ops/Cloud-OpsBench>
- Cloud-OpsBench paper: <https://arxiv.org/abs/2603.00468>
