# M13.1 Nested Validation Results

This is a strict outer grouped estimate of the frozen M13 selection procedure.
No outer-test incident participated in configuration or architecture selection.

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| chance | 0.0667 | 0.1417 | 0.1917 | 0.3667 | 0.8333 | 0.2342 | 1.0000 |
| metric_heuristic | 0.3500 | 0.4333 | 0.5250 | 0.6083 | 0.9833 | 0.4942 | 1.0000 |
| frozen_m11 | 0.3833 | 0.4333 | 0.4917 | 0.5083 | 0.8750 | 0.4865 | 1.0000 |
| nested_selected_procedure | 0.8833 | 0.9667 | 0.9917 | 1.0000 | 1.0000 | 0.9354 | 1.0000 |

## Fold-level selection

| Outer fold | Selected architecture | depth | eta | rounds | Outer AC@1 | Outer MRR |
|---:|---|---:|---:|---:|---:|---:|
| 0 | full_candidate_challenger | 2 | 0.08 | 24 | 0.8750 | 0.9271 |
| 1 | full_candidate_challenger | 3 | 0.08 | 48 | 0.7917 | 0.8819 |
| 2 | full_candidate_challenger | 3 | 0.08 | 48 | 0.9583 | 0.9792 |
| 3 | full_candidate_challenger | 3 | 0.08 | 48 | 0.8750 | 0.9306 |
| 4 | full_candidate_challenger | 3 | 0.08 | 48 | 0.9167 | 0.9583 |

Selection stability: `{"architecture_counts": {"full_candidate_challenger": 5}, "config_counts": {"{\"eta\": 0.08, \"max_depth\": 2, \"rounds\": 24}": 1, "{\"eta\": 0.08, \"max_depth\": 3, \"rounds\": 48}": 4}}`.

Nested minus original M13 headline: AC@1
`-0.0083`, MRR
`-0.0012`. This difference is a
method-selection optimism diagnostic, not a new tuning target.

`FINAL_TEST_READY = YES`.

The result remains development-only. OpenTelemetry Astronomy Shop was not
cloned, deployed, faulted or scored.
