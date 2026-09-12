# M13 Results

Development-only result on DeathStarBench Social Network; the reserved final
system was not deployed or scored.

| Model | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| chance | 0.0667 | 0.1417 | 0.1917 | 0.3667 | 0.8333 | 0.2342 |
| metric_heuristic | 0.3500 | 0.4333 | 0.5250 | 0.6083 | 0.9833 | 0.4942 |
| frozen_m11 | 0.3833 | 0.4333 | 0.4917 | 0.5083 | 0.8750 | 0.4865 |
| extended_full_top5 | 0.4833 | 0.5083 | 0.5083 | 0.5083 | 0.8750 | 0.5512 |
| two_expert_fusion_top5 | 0.4917 | 0.5083 | 0.5083 | 0.5083 | 0.8750 | 0.5554 |
| full_candidate_challenger | 0.8917 | 0.9583 | 0.9833 | 1.0000 | 1.0000 | 0.9367 |

Selected: **full_candidate_challenger**. Research champion decision:
**PROMOTE_M13_RESEARCH_CHAMPION**.

Primary figures are repetition-isolated grouped OOF within the development
system. Complementary leave-one-root-out AC@1/MRR are
0.7083/
0.8219; leave-one-fault-family-out
AC@1/MRR are 0.6417/
0.7424. These harder diagnostics
are not a substitute for the still-reserved final-system test.

- Trace incremental value: SUPPORTED
- Disappearance evidence: PARTIALLY_SUPPORTED
- Propagation evidence: SUPPORTED
- Learned vs metric heuristic: SUPPORTED
- Full-candidate reranking: PROMOTED
- GNN: NOT_JUSTIFIED
- Reliability V3: NOT_RUN
- Protocol deviations: `["warm-up below preferred 300 seconds", "baseline below preferred 900 seconds"]`
