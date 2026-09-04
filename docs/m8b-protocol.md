# M8B protocol: external validation on RCAEval

Protocol version: `m8b-v1`. This protocol was locked after the label-blind Phase-0 schema audit and before any external ranking was evaluated against ground truth.

## Pinned sources

- RCAEval repository: `https://github.com/phamquiluan/RCAEval`, commit `405c8fd24071af41ceb4b3aabb451e5e3e15d6c6` (package version 1.7.0).
- Hugging Face dataset: `phamquiluan/RCAEval`, revision `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`.
- `cases.parquet` SHA256: `c49a288920dbba2e8e724679a14636d5c7eb2b45426bba14007ef79a6c0ab1bb`.
- Fetch date: 2026-09-04.
- Audit runtime: Python 3.14.5, pandas 3.0.2, pyarrow 24.0.0, numpy 2.4.4.

Raw RCAEval data live under ignored `external-data/rcaeval/` and are never committed.

## Primary corpus

The corpus is the complete trace-capable subset selected from the pinned case index before evaluation:

| Dataset | Cases | Included |
|---|---:|---|
| RE2-OB | 90 | yes |
| RE2-TT | 90 | yes |
| RE3-OB | 30 | yes |
| RE3-TT | 30 | yes |
| RE1 | 375 | no: metric-only |
| RE2-SS | 90 | no: no traces |
| RE3-SS | 30 | no: no traces |

Expected primary denominator: 240 cases. Every expected case receives an explicit terminal status; no case is silently dropped.

## Truth isolation

The telemetry adapter receives only an opaque `external_case_id`, injection timestamp, and trace rows. It does not receive the case path, directory basename, root service, fault name, repetition, or any filename-derived token. Ground truth is loaded by a separate label adapter and joined only after truth-free feature snapshots and rankings have been persisted. Renaming or relocating a trace file must not change numeric features.

Label-side service normalization is locked to lowercase/trim plus underscore-to-hyphen conversion. The only explicit benchmark alias is Online Boutique `frontend` → `frontendservice`, observed during the label-blind schema audit. No generic suffix insertion/removal and no ranking-dependent mapping are allowed. A normalized root absent from observed telemetry is `root_not_observable`.

## Normalized span contract

Each source row becomes:

- trace ID, span ID, parent span ID;
- `serviceName` from telemetry;
- canonical operation name;
- start and end timestamps;
- duration;
- mapped error state;
- inferred span kind plus `kind_inferred=true`.

`startTime` and `duration` are microseconds. `time` is presentation-only `HH:MM` and is ignored. Operation uses `methodName` when present, otherwise `operationName`; query strings are removed and UUID or all-numeric path segments are replaced syntactically. No root-aware normalization is allowed.

RCAEval has no span-kind column. Kind is inferred structurally and uniformly: a span with an empty parent ID, or a child whose observed parent belongs to another service, is `server`; a same-service span with a direct child in another service is `client`; all other spans are `internal`. A non-empty missing parent is not treated as a root. The inference flag and coverage are reported.

Topology is reconstructed only from observed cross-service parent-child transitions. Active topology uses post-injection current-window traces; fallback topology uses the locked baseline and current horizons from the same case. No published system diagram is used.

## Locked windows and M5 configuration

Fault evaluation uses one label-independent protocol for all cases:

- baseline horizon: `[inject_time - 600 s, inject_time)`;
- current horizon: `[inject_time, inject_time + 600 s)`;
- a span belongs to a horizon only when its start is inside it;
- no post-injection span enters baseline;
- M5 keeps at most the last 1,000 baseline observations per operation and the last 20 current observations per operation, in timestamp/span-ID order.

Held-out pseudo-healthy evaluation uses non-overlapping pre-injection segments:

- healthy baseline: `[inject_time - 600 s, inject_time - 300 s)`;
- healthy current: `[inject_time - 300 s, inject_time)`.

Cases without the required data remain in the denominator with an explicit insufficient-data status.

The unchanged detector parameters are:

- minimum baseline samples: 30;
- maximum baseline samples: 1,000;
- current window size: 20;
- minimum current samples: 10;
- latency Z threshold: 3.5;
- error Z threshold: 3.0;
- robust-scale epsilon: 0.1;
- minimum active-topology trace coverage: 0.7.

Latency uses the existing Go M5 `log1p`, median, MAD and robust-scale implementation. M6 features and deterministic baselines use the existing Go diagnosis package.

## Error mapping

`statusCode` is absent in Train Ticket and therefore produces missing error evidence, never synthetic success/error data. For Online Boutique, zero is success; documented gRPC canonical non-zero codes 1..16 are errors; HTTP-like codes 400 and above are errors. Null is missing. Error-evidence coverage is reported separately.

## Evaluation order

1. Persist truth-free adapter output and frozen-M7 rankings for all 240 cases.
2. Seal their hashes in the run manifest.
3. Join pinned case-index ground truth by opaque case ID.
4. Report status coverage, detection, root observability, localization eligibility, conditional metrics and end-to-end metrics.
5. Report all four datasets, all fault families and RE2/RE3 separately.
6. Only after the zero-shot report is sealed may external system-holdout training run.

Frozen M7 remains `m7-lambdamart-v1`, SHA256 `3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699`. M5 thresholds, `m7-v1` feature columns and M7 hyperparameters are not tuned on RCAEval.

## Locked verdict mapping

Verdicts are descriptive gates fixed before the 240-case truth join. Detector is `ACCEPTABLE` only with recall at least 0.80 and healthy FPR at most 0.10, `LIMITING` with recall at least 0.40 otherwise, and `FAILED` below that. Feature representation is `STRONG_TRANSFER` when the best unchanged M6 baseline exceeds conditional chance AC@1 by at least 0.20, `PARTIAL_TRANSFER` when it merely exceeds chance, and `FAILED_TRANSFER` otherwise. Frozen M7 uses the same conditional AC@1 lift gates. Adapter parity is `PARTIAL_PARITY` because span kind must be inferred in every suite and Train Ticket lacks status/error evidence, even though the exact Go M5/M6 mathematics are reused. A limiting detector selects `REDESIGN DETECTOR FIRST` and `ADD TEMPORAL FEATURES`; LambdaMART is retained unless its zero-shot transfer fails.
