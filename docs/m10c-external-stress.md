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

Official sources checked during protocol preparation:

- RCAEval repository and baseline/data instructions: <https://github.com/phamquiluan/RCAEval>
- TORAI processed RE2 data: <https://doi.org/10.6084/m9.figshare.31925976>
- Cloud-OpsBench repository: <https://github.com/LLM4Ops/Cloud-OpsBench>
- Cloud-OpsBench paper: <https://arxiv.org/abs/2603.00468>

