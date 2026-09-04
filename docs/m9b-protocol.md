# M9B protocol: multi-source soft-evidence RCA v2

M9B evaluates root-cause localization conditioned on an external incident trigger. Autonomous M5/v1 detection remains a secondary end-to-end view. M5/v1, M7, M8A, M8B, and the rejected M9A CUSUM detector are immutable historical baselines; detector-v2 is not used.

## Pinned source and isolation

RCAEval source commit is `405c8fd24071af41ceb4b3aabb451e5e3e15d6c6`, Hugging Face revision is `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`, and cases-index SHA256 is `c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb`. Feature extraction receives metric/trace telemetry, timestamps, dataset/system routing metadata, and an opaque case identifier, but no root or fault label. Features are fsync-persisted and SHA256-sealed before labels are read. Case names, paths, entity strings, operations, systems, datasets, roots, and faults are forbidden model features.

## Candidate universe and entity mapping

Triggered localization ranks every observable feature-ready service; `latency_anomalous` and `error_anomalous` are features, never inclusion gates. Metric-only systems use normalized non-infrastructure metric entities as services. Where traces exist, a metric entity is accepted only if its lowercase/hyphen-normalized identity, after removing a terminal `service`, uniquely matches an observed trace service. `redis`, `rabbitmq`, `queue`, `session`, `istio-proxy`, and entities ending in `-mongo`, `-mysql`, or `-db` remain unmatched infrastructure. Labels never change this mapping.

## Metric parsing and windows

The strict suffix map is `_cpu`, `_mem`, `_diskio`, `_socket`, `_workload`, `_error`, `_latency-50`, and `_latency-90`, mapped to `cpu`, `memory`, `disk_io`, `socket`, `workload`, `error`, `latency_p50`, and `latency_p90`. Unknown columns are ignored and counted.

RCAEval fault windows are baseline `[inject-600s, inject)` and current `[inject, inject+600s)`. Frozen M5/v1 autonomous controls remain the M8B non-overlapping pre-injection controls; M9B introduces no second detector and therefore does not use healthy controls in its primary triggered-localization score. Cadence, duplicate timestamps, missing timestamps, NaN, and Inf are audited rather than assumed. Duplicate timestamps, if present, are collapsed by per-timestamp median before feature extraction.

For each channel, baseline location is the median, scale is `max(1.4826*MAD, 1e-6*max(1, abs(baseline_median)))`, and the exceedance threshold is `|residual| >= 3.5`. Features include baseline/current sample counts, signed/absolute median shift, p90 and IQR shift, persistence, normalized maximum run, first-exceedance and peak fractions, plus maximum, median, and above-threshold fraction of rolling-median shifts over fixed 30s/60s/120s windows. No unbounded or sample-count-dependent cumulative sum is used.

Within a service/family, aggregation preserves maximum shift, top-two mean shift, maximum persistence, availability count, and the winning metric only for explanation. Missing families have mask `0` and numeric values `0`. Incident-relative percentiles are computed among candidates for metric evidence and selected trace/topology scores. Schema is `m9b-v1`.

## Baselines and models

Explainable baselines are `metric_max_shift`, `metric_top2`, `soft_topology_v1`, `soft_trace_v1`, `soft_hybrid_v1`, and unweighted normalized `rank_fusion_v1`. For rank fusion, a rank is mapped to `1-(rank-1)/(N-1)`, or `1` when `N=1`, then averaged across available modality rankings.

`m9b-metric-lambdamart-v1` uses metric numeric features, masks, and relative percentiles only. RE1-OB/SS/TT are development data. System holdouts are OB+SS→TT, OB+TT→SS, and SS+TT→OB, with deterministic hash validation inside training systems. Final hyperparameters are chosen by mean internal-validation MRR/AC@1 across folds, then frozen before RE2/RE3.

`m9b-multisource-lambdamart-v1` uses metrics, soft M7 trace evidence, topology, masks, and relative percentiles. RE2-OB→RE2/RE3-TT and RE2-TT→RE2/RE3-OB are cross-system folds. RE3 is evaluation-only before the first sealed result. M7-style LambdaMART parameters are the starting search family; test systems never tune a fold.

Modality ablation retrains metrics-only, traces-only, topology-only, each pair, and all modalities on the same training folds. Metric one-group-drop ablation removes CPU, memory, disk I/O, socket, workload, latency-p50, or latency-p90 from a model retrained on RE1.

## Evaluation and verdict

Primary metrics are triggered AC@1, AC@3, and MRR on root-observable feature-ready cases. Coverage is reported separately. Secondary autonomous evaluation is frozen M5/v1 detection followed by the M9B ranking; detector-v2 is excluded.

The primary paired comparison is best M9B method minus the best unchanged soft trace-only baseline over identical trace-capable cases, with 2,000 incident bootstrap resamples and seed `20260904`.

- `STRONG_MULTISOURCE_GAIN`: AC@1 difference at least `0.10` and bootstrap lower bound above zero.
- `PARTIAL_MULTISOURCE_GAIN`: AC@1 difference at least `0.05` or MRR difference at least `0.05`.
- `NO_JUSTIFIED_GAIN`: otherwise.

Code-fault coverage is `IMPROVED` when mean RE3 AC@1 rises by at least `0.05` over the selected trace-only baseline, `UNCHANGED` within `0.05`, and `FAILED` below that range. These rules are descriptive gates and cannot be changed after results are observed.
