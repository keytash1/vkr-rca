# M14 Claim Registry

Final status: **SUPPORTED_TRANSFER / USED_TEST / FINAL_RESEARCH_FREEZE**.
One-time opening on 2026-09-13; 50 incidents, 25 root/fault clusters. The primary
comparison interval is a 10,000-resample paired cluster bootstrap (95%).

| Claim | Observed status | Evidence | Boundary |
|---|---|---|---|
| Frozen M13 transfers to a new system for represented fault families | SUPPORTED_TRANSFER | Coverage 1.00; AC@1 .50, AC@3 .70, AC@5 .78, MRR .629955; all comparator gates pass | One controlled Astronomy Shop deployment |
| Frozen M13 beats chance | SUPPORTED | AC@1 delta .44, CI [.26, .62]; MRR delta .403608, CI [.240950, .556892] | Same 50 incidents |
| Frozen M13 beats generic metric heuristic | SUPPORTED | AC@1 delta .20, CI [.04, .36]; MRR delta .174452, CI [.058594, .302740] | Same 50 incidents |
| Frozen M13 beats frozen M11 | SUPPORTED | AC@1 delta .34, CI [.18, .52]; MRR delta .247633, CI [.094974, .407842] | Same 50 incidents |
| Strong cross-system transfer | NOT_SUPPORTED | AC@3 .70 < .80 and AC@5 .78 < .90 | Do not upgrade the registered verdict |
| Uniform strength across services or fault families | NOT_ESTABLISHED | Payment AC@1 .10; ad AC@5 .50; packet-loss AC@1 .30 | Small groups, n=10 each |
| Universal RCA, arbitrary unseen fault families, causal proof, calibrated probability, production readiness or MTTR reduction | NOT_ESTABLISHED | Not measured by this protocol | Forbidden thesis claims |

The exact pooled/grouped metrics, Wilson intervals, both bootstrap units and
all errors are in `ml/models/m14/evaluation.json`. Full interpretation and
deployment limitations are in `docs/m14-results.md`. Historical M12 weakness,
M13 ablations and M13.1 nested estimates remain unchanged; M14 does not turn
development results into independent final-test evidence. No post-test tuning.
