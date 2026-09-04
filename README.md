# RCA for distributed services

Milestone 6 of the RCA graduation project: a synchronous Go service chain with controlled faults, end-to-end OpenTelemetry tracing, topology reconstruction, statistical anomaly detection, and explainable root-cause ranking over real OTLP spans.

```text
Client -> Gateway -> Orders -> Payment
              \         |         /
               OTLP/gRPC spans
                     |
                         +-> Jaeger
              OTel Collector
                         +-> RCA OTLP receiver -> service graph
                                               -> frozen baseline -> anomaly scores
                                                                  -> RCA features -> rankings
```

One request creates a single distributed trace containing the server and client spans for all three services. Gateway, Orders, and Payment expose development-only controls for reproducible faults. The RCA service receives a second copy of those spans, derives service dependencies without knowing the topology in advance, compares operation-level latency and error rate with an explicitly collected healthy baseline, and ranks anomalous services using topology and trace-local evidence.

## Requirements

- Docker with Docker Compose
- `curl` for smoke requests
- Go 1.26 only for running outside Docker

## Run

Build the images, start the stack, and wait for application health checks:

```bash
docker compose up --build -d --wait
```

Generate a distributed trace:

```bash
make trace-smoke
```

Equivalent request:

```bash
curl --fail --silent --show-error \
  --header 'X-Request-ID: milestone-2-smoke' \
  http://localhost:18080/api/order
```

Expected response:

```json
{"service":"gateway","order":{"order_id":"demo-order","status":"confirmed","payment":{"provider":"payment","status":"authorized"}}}
```

Open [Jaeger UI](http://localhost:16686), select the `gateway` service, and find traces. A successful trace includes resources with all three service names:

```text
gateway -> orders -> payment
```

There are normally five spans rather than exactly three: a server span for each service plus client spans for Gateway -> Orders and Orders -> Payment.

Stop the stack:

```bash
docker compose down --remove-orphans
```

Shortcuts are available as `make compose-up`, `make smoke`, `make trace-smoke`, `make graph-smoke`, `make baseline-smoke`, `make anomaly-smoke`, `make rca-smoke`, `make logs`, and `make compose-down`.

## Trace and request correlation

HTTP context propagation uses the standard W3C `traceparent` format and OpenTelemetry Baggage. Applications export spans over OTLP/gRPC to the Collector; the Collector batches and exports them over OTLP to Jaeger.

`X-Request-ID` remains independent of OpenTelemetry identifiers. It is returned to the caller and propagated through the complete chain. Structured application logs include:

- `request_id`;
- `trace_id`;
- the current server `span_id`.

For one application request, all three services log the same `request_id` and `trace_id`, while their server `span_id` values differ. Health checks are excluded from tracing to keep Jaeger clean.

## Milestone 3: controlled fault injection

Gateway, Orders, and Payment each own an independent, in-memory fault injector. Configuration changes take effect without restarting containers and are safe under concurrent requests. The debug API is intended only for this local experiment; it has no authentication and must not be exposed as a production control plane.

Fault configuration:

```json
{
  "latency_ms": 700,
  "error_rate": 0.0
}
```

- `latency_ms` must be non-negative. The delay respects request context cancellation.
- `error_rate` must be between `0.0` and `1.0`. `0.0` never fails, `1.0` always fails, and intermediate values use a pseudo-random decision per request.
- Updating the config replaces both fields; omitted JSON fields therefore become zero.

Development endpoints on Gateway (`:8080`), Orders (`:8081`), and Payment (`:8082`):

| Endpoint | Purpose |
| --- | --- |
| `GET /debug/fault` | Read current configuration |
| `POST /debug/fault` | Replace configuration with a strict JSON object |
| `POST /debug/reset` | Restore `{ "latency_ms": 0, "error_rate": 0 }` |

Unknown JSON fields and invalid values return `400`; a non-JSON update returns `415`. Faults affect only the service business endpoint: `/api/order`, `/orders/current`, or `/payments/authorize`. Health and debug endpoints are never delayed or failed and are excluded from tracing. A Gateway-local error stops the chain before Orders is called.

Convenient demo commands:

```bash
make fault-status
make fault-gateway-latency
make fault-payment-latency
make fault-orders-latency
make fault-gateway-errors
make fault-payment-errors
make fault-reset
```

`fault-payment-errors` configures a 50% error rate for interactive demos. Use `error_rate: 1.0` for deterministic tests.

### Reproducible scenarios

Payment latency:

```text
Gateway slow -> Orders slow -> Payment slow
```

Payment waits locally before responding, so both upstream callers naturally include that wait in their spans.

Orders latency with healthy Payment:

```text
Gateway slow -> Orders slow -> Payment normal
```

Orders waits before calling Payment. This distinction will later prevent RCA from blindly selecting the deepest downstream service.

Payment error with `error_rate: 1.0`:

```text
Payment 500 -> Orders 502 -> Gateway 502
```

No special propagation logic is added: the existing downstream error handling produces this chain naturally. Reset both injectors afterwards with `make fault-reset`.

## Milestone 4: service graph reconstruction

The Collector fans each trace out over OTLP/gRPC to both Jaeger and the RCA service. Jaeger remains the visual verification tool; RCA implements the graph builder itself and does not use the Collector Service Graph Connector, Jaeger API, application logs, hostnames, URLs, or hardcoded service names.

RCA separates three layers:

1. the official OTLP `TraceServiceServer` transport converts protobuf messages into a small normalized `Span` model;
2. the bounded trace store joins spans by `TraceID`, `SpanID`, and `ParentSpanID`;
3. the graph snapshot aggregates cross-service parent-child relationships.

`service.name` is read only from the OpenTelemetry Resource. Spans without a valid identity or `service.name` are ignored, counted, and reported as OTLP partial success instead of creating guessed nodes.

For the normal five-span hierarchy:

```text
Gateway SERVER [gateway]
└── Gateway CLIENT [gateway]
    └── Orders SERVER [orders]
        └── Orders CLIENT [orders]
            └── Payment SERVER [payment]

                         ↓

gateway -> orders -> payment
```

A relation creates an edge only when its parent and child belong to different services. Same-service SERVER/CLIENT nesting therefore creates no self-edge. Missing parents create no synthetic `external` node. Span kind is retained as evidence but deliberately not used as a strict gate: the parent-child identity and differing service names are authoritative, so imperfect instrumentation cannot erase an otherwise observable dependency.

Spans may arrive child-first or in different exports. Each retained trace keeps pending parent-child relationships and links them when both sides become available. `TraceID + SpanID` is the deduplication key, making Collector retries idempotent while that trace is retained. Edge observations count unique cross-service span relationships.

Raw normalized spans are in memory for `TRACE_TTL` (default `10m`) with at most `MAX_TRACES` trace states (default `5000`). Cleanup happens during ingestion and reads; the oldest state is evicted at the limit. The aggregated graph remains until the RCA process exits or is explicitly reset. A duplicate arriving after its trace state has expired is outside the deduplication window and can be counted again.

RCA HTTP API on host port `18090`:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | RCA process health |
| `GET /api/graph` | Deterministically sorted nodes and edges |
| `GET /api/traces/{trace_id}` | Retained normalized spans for one trace |
| `POST /debug/reset` | Clear retained spans and the aggregated graph |

RCA is intentionally not instrumented into the same trace pipeline, preventing it from adding itself to the graph. The inspection and reset API is development-only and has no authentication.

Run the deterministic healthy topology demo:

```bash
make graph-smoke
```

It resets RCA and all three fault injectors, sends ten Gateway requests, waits for batching, and prints `/api/graph`. No `jq` dependency is required.

## Milestone 5: healthy baseline and anomaly detection

The detector consumes only deduplicated `SERVER` spans. `CLIENT` spans are ignored so one RPC is not counted twice, and `/health` plus `/debug/*` are excluded. An operation key is `service.name + HTTP method + http.route` when route metadata exists; the span name is the fallback. HTTP statuses `500` and above are failures, `4xx` responses are not, and OpenTelemetry `StatusError` is used only when an HTTP status is absent.

Baseline lifecycle is explicit:

```text
EMPTY --POST /debug/baseline/start--> COLLECTING
  ^                                      |
  |                                  collect healthy spans
  |                                      |
  +--another start resets everything-----+
                                         |
                         POST /debug/baseline/freeze
                                         |
                                      FROZEN
                                         |
                         collect rolling current windows
```

Freezing makes the baseline immutable and clears the current windows. `POST /debug/anomaly/reset` clears only current observations and preserves the frozen baseline. Baseline samples are bounded by `MAX_BASELINE_SAMPLES` per operation; the current side retains only the latest `CURRENT_WINDOW_SIZE` observations.

For every latency `latency_ms`, the detector uses the stabilising transform:

```text
x = ln(1 + latency_ms)
baseline_location = median(x_baseline)
MAD = median(abs(x_baseline - baseline_location))
robust_scale = max(1.4826 * MAD, ROBUST_SCALE_EPSILON)
latency_z = max(0, (median(x_current) - baseline_location) / robust_scale)
```

The non-negative score deliberately detects regressions, not unusually fast responses. The response also includes raw millisecond medians and nearest-rank p95 values for interpretation. A single latency spike cannot move the median of the default 20-request window enough to trigger a sustained anomaly.

For failures, with baseline errors `e0` out of `n0` and current errors `e1` out of `n1`:

```text
p0 = (e0 + 0.5) / (n0 + 1)
p1 = e1 / n1
pooled = (e0 + 0.5 + e1) / (n0 + 1 + n1)
error_z = max(0, (p1 - p0) /
                    sqrt(pooled * (1 - pooled) * (1/(n0 + 1) + 1/n1)))
```

Degenerate zero-variance cases return a finite zero score. An operation is evaluated only after the configured minimum baseline and current sample counts. Before then its state is `insufficient_baseline` or `insufficient_current_data`, never an anomaly.

Default thresholds are `latency_z >= 3.5` and `error_z >= 3.0`. Operation severity is intentionally unclamped:

```text
severity = max(latency_z / 3.5, error_z / 3.0)
```

Service severity is the maximum severity of its operations, and a service is anomalous when any operation is anomalous. Results are sorted lexically by service and operation for deterministic output.

RCA baseline and anomaly API on host port `18090`:

| Endpoint | Purpose |
| --- | --- |
| `POST /debug/baseline/start` | Clear all detector state and start healthy calibration |
| `GET /api/baseline` | Inspect lifecycle state and per-operation baseline statistics |
| `POST /debug/baseline/freeze` | Freeze calibration and clear current windows |
| `POST /debug/anomaly/reset` | Clear current windows without changing the baseline |
| `GET /api/anomalies` | Inspect deterministic operation and service anomaly results |

Create a healthy 50-request baseline and freeze it:

```bash
make baseline-smoke
```

Run the same calibration followed by 20 requests with Payment latency of 700 ms:

```bash
make anomaly-smoke
```

Both targets wait for Collector batching and validate JSON with standard shell tools; `jq` is not required. `anomaly-smoke` resets fault injection after traffic generation.

Milestone 5 is a statistical detector. Its output remains independently inspectable and is the anomaly input for Milestone 6.

## Milestone 6: explainable RCA baselines

Milestone 6 ranks only currently anomalous services. It combines M5 anomaly evidence, M4 topology, and trace-local exclusive observed duration without using ground truth during feature extraction or ranking. The complete feature definitions, algorithms, equations, and limitations are documented in [RCA v0.1](docs/rca-v1.md).

The preferred incident graph is rebuilt from the exact retained traces referenced by the current M5 window. When its trace coverage is below `MIN_ACTIVE_TOPOLOGY_COVERAGE`, the API reports `global_fallback` and uses the aggregated M4 graph explicitly. This prevents a historical branch from silently contaminating a well-covered current incident.

Inspect the evidence and four deterministic rankings:

```bash
curl --fail --silent --show-error http://localhost:18090/api/features
curl --fail --silent --show-error http://localhost:18090/api/rca
```

Run the end-to-end acceptance matrix for healthy traffic plus latency and error faults at Payment, Orders, and Gateway:

```bash
make rca-smoke
```

The smoke test checks the observed anomalies and the expected `hybrid_v1` Top-1 result using externally supplied scenario labels. It also validates the public schema, active-topology use, deterministic response shape, and absence of truth leakage. Scores are explainable heuristic evidence strengths, not probabilities or confidence estimates. A learned model remains future work and is not part of this milestone.

## Endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `GET /api/order` | Public endpoint executing the complete chain |
| Gateway | `GET /health` | Liveness check |
| Orders | `GET /orders/current` | Calls Payment and returns the demo order |
| Orders | `GET /health` | Liveness check |
| Payment | `GET /payments/authorize` | Returns the demo authorization result |
| Payment | `GET /health` | Liveness check |
| Gateway / Orders / Payment | `GET/POST /debug/fault` | Read or replace local fault configuration |
| Gateway / Orders / Payment | `POST /debug/reset` | Reset local fault configuration |
| RCA | `GET /api/graph` | Current service graph |
| RCA | `GET /api/traces/{trace_id}` | Retained normalized trace |
| RCA | `POST /debug/reset` | Reset trace and graph state |
| RCA | `GET /api/baseline` | Current healthy baseline statistics |
| RCA | `GET /api/anomalies` | Current operation and service anomaly scores |
| RCA | `GET /api/features` | Explainable M6 feature snapshot and topology source |
| RCA | `GET /api/rca` | Four deterministic root-cause candidate rankings |
| RCA | `POST /debug/baseline/start` | Start a new baseline calibration |
| RCA | `POST /debug/baseline/freeze` | Freeze the collected baseline |
| RCA | `POST /debug/anomaly/reset` | Reset current anomaly windows only |
| RCA | `GET /health` | Liveness check |

Unsupported methods on defined endpoints return `405 Method Not Allowed`. A downstream failure is exposed to the caller as `502 Bad Gateway`.

## Local checks

```bash
make fmt
make test
make build
go vet ./...
go test -race ./...
```

The tests cover handlers, fault behavior, trace propagation, the graph algorithm, out-of-order ingestion, duplicate exports, retention, concurrent ingestion, deterministic output, strict RCA HTTP behavior, robust statistics, detector lifecycle and bounds, latency and error anomalies, threshold boundaries, CLIENT-span exclusion, active-incident topology and fallback, cycle-safe reverse reachability, exclusive-duration interval union, all four rankers, truth-free evaluation, and synthetic OTLP requests containing the real five-span hierarchy. Tests do not require an external Collector.

## Configuration

| Variable | Service | Default outside Docker |
| --- | --- | --- |
| `HTTP_ADDR` | all | `:8080`, `:8081`, `:8082`, or RCA `:8090` |
| `ORDERS_URL` | Gateway | `http://orders:8081` |
| `PAYMENT_URL` | Orders | `http://payment:8082` |
| `HTTP_CLIENT_TIMEOUT` | Gateway / Orders | `3s` / `2s` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | `localhost:4317` |
| `OTEL_EXPORTER_OTLP_INSECURE` | all | `true` |
| `OTLP_ADDR` | RCA | `:4317` |
| `TRACE_TTL` | RCA | `10m` |
| `MAX_TRACES` | RCA | `5000` |
| `MIN_BASELINE_SAMPLES` | RCA | `30` |
| `MAX_BASELINE_SAMPLES` | RCA | `1000` |
| `CURRENT_WINDOW_SIZE` | RCA | `20` |
| `MIN_CURRENT_SAMPLES` | RCA | `10` |
| `LATENCY_Z_THRESHOLD` | RCA | `3.5` |
| `ERROR_Z_THRESHOLD` | RCA | `3.0` |
| `ROBUST_SCALE_EPSILON` | RCA | `0.1` |
| `MIN_ACTIVE_TOPOLOGY_COVERAGE` | RCA | `0.7` |

Compose sets the OTLP endpoint to `otel-collector:4317`. The `service.name` resource attribute is fixed in each binary as `gateway`, `orders`, or `payment`.

Host ports default to:

- Gateway: `18080`;
- Orders: `8081`;
- Payment: `8082`;
- RCA HTTP: `18090`;
- Jaeger UI: `16686`.

They can be overridden with `GATEWAY_PORT`, `ORDERS_PORT`, `PAYMENT_PORT`, `RCA_HTTP_PORT`, and `JAEGER_UI_PORT` without changing container-to-container addresses.

## Pinned observability components

- OpenTelemetry Go API, SDK, and OTLP trace exporter: `v1.45.0`;
- OpenTelemetry HTTP instrumentation: `v0.70.0`;
- OpenTelemetry OTLP protobuf: `v1.11.0`;
- gRPC-Go: `v1.83.0`;
- OpenTelemetry Collector Contrib: `0.158.0`;
- Jaeger v2: `2.20.0`.
