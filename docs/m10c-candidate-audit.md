# M10C candidate-generation audit

The audit was generated from the already sealed M9B truth-free telemetry. Every
candidate universe was materialized before root labels were opened. Detailed
machine-readable evidence is in
`artifacts/m10c/m10c-v2/candidate-audit.json`.

## Frozen blind spot

The agreed external denominator is the 360 RE2/RE3 cases. M10A observes the
root in 336 cases. All 24 missing cases are `RE3-OB`:

| Root | Cases | A-G class | Evidence |
|---|---:|---|---|
| `adservice` | 9 | B: metrics entity mapping rejected | Metric entity exists, but is absent from the partial trace universe and M9B rejects it. |
| `cartservice` | 3 | B: metrics entity mapping rejected | Same generic rejection path. |
| `emailservice` | 12 | B: metrics entity mapping rejected | Same generic rejection path. |

There is no evidence that these roots require infrastructure candidates or
case-specific aliases. They are ordinary non-infrastructure service entities
present in metrics. The previous adapter constrained metric mapping to the
observed trace universe, turning trace missingness into candidate missingness.

Two additional M9B misses exist in `RE1-OB`; they are outside the frozen 360
test denominator but are recovered by the same rule. They are reported here to
show that the correction was not fitted only to RE3 outcomes.

## Generic correction

The M10C candidate universe is:

`canonical non-infrastructure metric service entities UNION trace services`

A metric entity maps to a trace service only when its normalized service key
has one unambiguous match. Otherwise its normalized metric identity remains a
candidate. Candidate records explicitly carry `type`, `has_metrics`,
`has_traces` and `has_topology`. No root, fault or dataset identity is accepted
by the generation API. Infrastructure stays excluded from this primary
experiment; no typed infrastructure experiment is justified by the 24-case
audit.

## Coverage result before ranking

| Scope | Cases | Root observable | Candidate recall | Mean candidates |
|---|---:|---:|---:|---:|
| RE1 | 375 | 375 | 1.000 | 21.149 |
| RE2 | 270 | 270 | 1.000 | 20.700 |
| RE3 | 90 | 90 | 1.000 | 21.033 |
| RE2 + RE3 external | 360 | 360 | 1.000 | 20.783 |
| RE2-OB | 90 | 90 | 1.000 | 11.022 |
| RE2-SS | 90 | 90 | 1.000 | 9.022 |
| RE2-TT | 90 | 90 | 1.000 | 42.056 |
| RE3-OB | 30 | 30 | 1.000 | 11.533 |
| RE3-SS | 30 | 30 | 1.000 | 9.333 |
| RE3-TT | 30 | 30 | 1.000 | 42.233 |

Root Observable Coverage therefore changes from 336/360 to 360/360 before any
ranking model is trained. The cost is a larger, more honest universe: mean
external candidates rise because service metric entities are no longer erased
when traces omit them. All later accuracy metrics use this full universe and
the unchanged 360-case denominator.

