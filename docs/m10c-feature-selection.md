# M10C feature stability and workload conditioning

## Candidate representation

The source-independent `m10c-v2-candidate` schema has 90 numeric columns versus
253 in M9B, a 64.4% reduction. It represents 13 canonical metric families,
incident-relative percentiles, trace/exclusive-duration/downstream-wait
evidence, topology, availability/coverage masks and four workload-conditioned
residual features. Unsupported families are explicit zero-plus-mask values;
the core does not depend on RCAEval column names.

## Training-only stability selection

Nine models were fitted across three RE1 system holdouts and three fixed seeds.
For every feature the audit records usage frequency, normalized total gain and
within-incident permutation MRR contribution. Non-structural eligibility needs
both use and positive permutation contribution in at least 60% of models;
availability, coverage and topology fields use the pre-registered structural
exception.

The strict selector retained 32 columns. On RE1 system holdouts:

| Schema | Mean AC@1 | Mean MRR |
|---|---:|---:|
| 90-column candidate schema | 0.7685 | 0.8463 |
| 32-column stability subset | 0.7681 | 0.8590 |
| Delta | -0.0005 | +0.0127 |

It therefore passes the compact gate. On the separate 60-case calibration and
fusion-selection partition it also beat stacked late fusion (MRR 0.9483 versus
0.9358). The selected challenger consequently uses 32 telemetry features, an
87.4% reduction from the frozen 253. No external result selected this subset.

## Workload-conditioned evidence

The implementation fits deterministic Huber IRLS only on each incident's
baseline window. Positive skew is transformed by a baseline-only rule. Current
residual location, P90, persistence and peak are then emitted.

RE1 system-holdout selection result:

| Variant | Mean AC@1 | Mean MRR |
|---|---:|---:|
| With residuals | 0.7685 | 0.8463 |
| Without residuals | 0.7428 | 0.8306 |
| Delta | +0.0257 | +0.0156 |

The hypothesis is promoted as a representation component on training-only
transfer evidence; no independent significance claim is made.
