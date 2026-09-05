# M10C modality experts and fusion

Metric and trace/topology LambdaMART experts produce scores for the identical
coverage-aware candidate universe. A deterministic split first reserves 60
RE1 incidents for calibration/selection. Meta-training uses only out-of-fold
expert predictions for the remaining 315 incidents: each is predicted by
experts trained on the other two systems. Neither feature selection nor an
expert sees the 60 labels. Selection uses MRR, AC@1 and finally simplicity.

## RE1 selection partition

| Method | AC@1 | MRR |
|---|---:|---:|
| Compact 32-feature model | **0.9167** | **0.9483** |
| Existing-style early fusion | 0.9000 | 0.9399 |
| Mean rank percentile | 0.4167 | 0.5856 |
| Reciprocal rank fusion | 0.4167 | 0.6000 |
| Stacked LambdaMART | 0.9000 | 0.9358 |

`compact_stability` was therefore frozen before the external test. The stacked
challenger used 15 derived meta-features—expert rank percentiles, relative
scores, margins, disagreement, modality masks, coverage, candidate count and
graph context—but was not selected.

## Frozen 360-case evaluation

| Method | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|
| Compact 32-feature model, pre-selected | **0.7889** | **0.9417** | **0.8690** |
| Early fusion | 0.7778 | 0.9444 | 0.8603 |
| Mean rank percentile | 0.2639 | 0.5500 | 0.4471 |
| Reciprocal rank fusion | 0.3139 | 0.5889 | 0.4951 |
| Stacked LambdaMART | 0.7222 | **0.9472** | 0.8306 |

The compact model wins both selection and final descriptive metrics. Static
rank fusion and RRF are rejected: the trace expert is weak under broad trace
missingness, and equal weighting destroys useful metric evidence. Stacking
partially avoids that failure but does not beat the compact representation.

Selected method by system:

| System | Cases | AC@1 | AC@2 | AC@3 | MRR |
|---|---:|---:|---:|---:|---:|
| Online Boutique | 120 | 0.8667 | 0.9333 | 0.9667 | 0.9162 |
| Sock Shop | 120 | 0.8500 | 0.9500 | 0.9667 | 0.9130 |
| Train Ticket | 120 | 0.6500 | 0.8167 | 0.8917 | 0.7778 |
