# M13 Error Analysis

Selected architecture: **full_candidate_challenger**.

Primary stages use the full 120-incident denominator for every serious model.

| Model | Success@1 | Within Top-3 | Within Top-5 | Below Top-5 | Below Top-10 | Universe miss |
|---|---:|---:|---:|---:|---:|---:|
| frozen_m11 | 46 | 13 | 2 | 44 | 15 | 0 |
| extended_full_top5 | 58 | 3 | 0 | 44 | 15 | 0 |
| two_expert_fusion_top5 | 59 | 2 | 0 | 44 | 15 | 0 |
| full_candidate_challenger | 107 | 11 | 2 | 0 | 0 | 0 |

Selected-model overlapping diagnostic hypotheses: `{"EXPECTED_SIGNAL_DISAPPEARANCE": 24, "LOW_WORKLOAD_SIGNAL": 60, "PROPAGATED_VICTIM_PATTERN": 59}`.

These flags are descriptive error hypotheses, not causal ground-truth labels.
The full machine-readable examples are in `ml/models/m13/evaluation.json`.
