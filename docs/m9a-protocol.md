# M9A protocol: temporal anomaly detector v2

M9A is an independent research experiment. The Go M5 detector, M8B truth-free artifact and frozen M7 model are immutable baselines. Detector v2 does not perform root-cause ranking.

## Hypothesis and selection

The hypothesis is that multi-scale temporal evidence improves short, late and gradual fault detection without unacceptable healthy false positives. Configuration is selected exclusively on deterministic synthetic A/B/C validation scenarios. A complete `scenario_id`, including all five repetitions, is assigned to development or validation by SHA256; overlap is forbidden.

Candidate families are frozen before external evaluation:

- M5/v1 single last-20-sample robust-median detector;
- `multiscale_location`;
- `multiscale_location_tail` with quantiles 0.90 and 0.95;
- positive `cusum` with `k` in 0.25, 0.5 and 1.0;
- `combined_temporal_v2`.

Temporal scales are 5, 10 and 20 observations. Candidate thresholds are enumerated by `detector_v2.config_grid`. Selection order is: highest synthetic-validation fault recall subject to healthy FPR <= 0.10, then lower FPR, then simpler algorithm/config, then lexical config hash.

The selected configuration is CUSUM with `k=0.25`, threshold `20.0`, error threshold `3.0`, baseline epsilon `0.1`, and config SHA256 `ad13f50171a21198bfda8ade4165ba0d03c1c5912a335346b22ad3ea456bf048`. It was frozen before any M9A external result was computed.

## Temporal contract

For latency, detector v2 uses the M5-compatible `log1p` baseline median, `1.4826*MAD`, and scale floor 0.1. Residuals are one-sided. The full current sequence remains timestamp ordered. Location, tail, CUSUM and error scores are emitted even when the selected family uses only a subset. Error evidence is `unavailable` when source statuses are missing; it is never replaced by observed healthy zeros.

Service score is the maximum operation score, with the winning operation retained. Output schema `m9a-temporal-v1` also records onset, selected scale, persistence, maximum exceedance run and valid sample counts. Scores are not probabilities.

## External evaluation

The external experiment is explicitly named **post-M8B frozen-detector-v2 evaluation**, not a new pristine zero-shot result. It reuses the pinned 240 RCAEval cases and the exact M8B fault and pseudo-healthy horizons. Detector output is persisted and SHA256-sealed before existing M8B labels are joined.

The external verdict gates were fixed by the accepted handoff:

- `STRONG_IMPROVEMENT`: recall difference >= 0.15 and overall v2 healthy FPR <= 0.10;
- `PARTIAL_IMPROVEMENT`: recall difference >= 0.05 and v2 FPR <= 0.15;
- `NOT_JUSTIFIED`: otherwise.

Paired tables, exact McNemar/binomial tests and paired bootstrap confidence intervals are reported. Incident detection and root-service anomaly recall remain separate.
