# M9B metrics adapter audit

This audit is computed over all 735 pinned metric cases without using root/fault labels during feature extraction.

## Time-series integrity

- Median cadence distribution: `{1.0: 735}`.
- Duplicate timestamps: `0`.
- Missing timestamps: `0`.
- NaN metric values: `1793140`.
- Infinite metric values: `0`.
- Unknown metric columns: `1105`.

## Mapping and candidate coverage

| Dataset | Cases | Root observable | Triggered eligible | Mean candidates | Entity match | Unmatched infrastructure |
|---|---:|---:|---:|---:|---:|---:|
| RE1-OB | 125 | 123 | 123 | 12.2 | 92.6% | 125 |
| RE1-SS | 125 | 125 | 125 | 9.0 | 60.0% | 750 |
| RE1-TT | 125 | 125 | 125 | 42.0 | 65.6% | 2750 |
| RE2-OB | 90 | 90 | 90 | 7.0 | 58.2% | 90 |
| RE2-SS | 90 | 90 | 90 | 9.0 | 60.1% | 540 |
| RE2-TT | 90 | 90 | 90 | 25.2 | 37.0% | 2340 |
| RE3-OB | 30 | 6 | 6 | 6.4 | 50.0% | 42 |
| RE3-SS | 30 | 30 | 30 | 9.0 | 60.7% | 181 |
| RE3-TT | 30 | 30 | 30 | 15.6 | 22.8% | 780 |

Metric-only datasets treat each normalized non-infrastructure metric entity as an observed service. Trace-capable datasets require a unique deterministic match to an observed trace service. Database/cache entities remain unmatched; labels never repair mappings.
