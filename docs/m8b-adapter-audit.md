# M8B Phase-0 adapter audit

The audit was performed before external predictions were evaluated. Sampling used the smallest SHA256 of `"m8b-phase0-v1:" + external_case_id` independently within each of the four primary datasets. Root service, fault type and performance were not selection inputs.

## Deterministic sample

| Dataset | External case ID | Rows |
|---|---|---:|
| RE2-OB | `re2ob_checkoutservice_delay_2` | 402,454 |
| RE2-TT | `re2tt_ts-train-service_delay_3` | 792,201 |
| RE3-OB | `re3ob_adservice_f5_1` | 162,900 |
| RE3-TT | `re3tt_ts-auth-service_f3_4` | 36,407 |

The IDs are recorded for reproducibility only. The adapter never parses them.

## Exact trace schema

All four Parquet files contain the same columns:

```text
time string
traceID string
spanID string
serviceName string
methodName string nullable
operationName string
parentSpanID string nullable
startTimeMillis int64
startTime int64
duration int64
statusCode int64 nullable
```

There is no span-kind field. `time` contains minute strings such as `12:43`, not an epoch. `startTime` is Unix microseconds, `startTimeMillis` is its millisecond duplicate, and `duration` is microseconds.

`methodName` is populated for Online Boutique and entirely absent for Train Ticket. `operationName` is populated in every sampled row and is therefore the fallback operation field.

`statusCode` is entirely absent for Train Ticket. RE2-OB contained only zero where present. The RE3-OB sample contained zero plus gRPC-like 4/13/14 and HTTP-like 400 values. The mapping is locked in `docs/m8b-protocol.md`; missing values remain missing.

## Temporal coverage

| Dataset | Pre-injection coverage | Post-injection coverage | Pre rows | Post rows | Injection-crossing spans |
|---|---:|---:|---:|---:|---:|
| RE2-OB | 720.0 s | 722.3 s | 204,281 | 198,173 | 4 |
| RE2-TT | 720.0 s | 721.8 s | 443,451 | 348,750 | 1 |
| RE3-OB | 719.6 s | 720.0 s | 82,759 | 80,141 | 0 |
| RE3-TT | 900.0 s | 899.7 s | 31,865 | 4,542 | 0 |

The common coverage supports fixed ten-minute fault horizons and two non-overlapping five-minute pseudo-healthy segments. Horizons were chosen from coverage, not label performance.

## Trace completeness and semantics

Span IDs were unique in every sample. Parent-ID match coverage was effectively complete: RE2-OB missed 2 observed non-empty parents, RE2-TT 30, RE3-OB 0 and RE3-TT 2. Root spans and cross-service parent-child transitions are visible. Online Boutique commonly records a same-service client span followed by a cross-service server child; Train Ticket shows the same structural pattern without an explicit kind field.

Observed service counts were 7 for both OB samples, 27 for RE2-TT and 20 for RE3-TT. No architecture diagram or case-name service is needed to reconstruct observed topology.

Because kind is inferred rather than supplied, adapter parity can be full for M5 statistics and M6 mathematics while exclusive-duration evidence remains coverage-qualified. Missing/unmatched parent structure yields missing exclusive evidence, not fabricated zero evidence.

Phase 0 did not execute ML rankings or compare any prediction with root-cause labels.
