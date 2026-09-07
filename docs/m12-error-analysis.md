# M12 Error Analysis

The final M11 Top-5 ranking has 23 Top-1 errors over the full
50-incident valid denominator. Primary mutually exclusive stages:
`{'WITHIN_TOP5_ORDERING_ERROR': 17, 'ROOT_BELOW_TOP5': 6}`. Overlapping descriptive flags: `{'MISSING_TRACES': 23, 'OOD_DOMAIN_SHIFT': 23}`.

Truth-rank histogram: `{'1': 27, '2': 6, '3': 6, '4-5': 5, '6-10': 6, '>10': 0, 'absent': 0}`.
Oracle candidate ceilings: `{'top_1': 0.54, 'top_3': 0.76, 'top_5': 0.88, 'top_10': 1.0}`.

Every error record is in `ml/models/m12/evaluation.json`. `MISSING_TRACES` means
the frozen canonical inference path had no trace vector; `OOD_DOMAIN_SHIFT`
describes the intentionally unseen domain and is not a causal diagnosis. No
incident was excluded because its anomaly was difficult for RCA to detect.
