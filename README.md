# RCA for distributed services

Milestone 3 of the RCA graduation project: a synchronous Go service chain with end-to-end OpenTelemetry tracing and controlled fault injection.

```text
Client -> Gateway -> Orders -> Payment
              \         |         /
               OTLP/gRPC spans
                     |
              OTel Collector -> Jaeger
```

One request creates a single distributed trace containing the server and client spans for all three services. Orders and Payment expose development-only controls for reproducible latency and HTTP error faults. Anomaly detection, service-graph reconstruction, and RCA logic are intentionally deferred to later milestones.

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

Shortcuts are available as `make compose-up`, `make smoke`, `make trace-smoke`, `make logs`, and `make compose-down`.

## Trace and request correlation

HTTP context propagation uses the standard W3C `traceparent` format and OpenTelemetry Baggage. Applications export spans over OTLP/gRPC to the Collector; the Collector batches and exports them over OTLP to Jaeger.

`X-Request-ID` remains independent of OpenTelemetry identifiers. It is returned to the caller and propagated through the complete chain. Structured application logs include:

- `request_id`;
- `trace_id`;
- the current server `span_id`.

For one application request, all three services log the same `request_id` and `trace_id`, while their server `span_id` values differ. Health checks are excluded from tracing to keep Jaeger clean.

## Milestone 3: controlled fault injection

Orders and Payment each own an independent, in-memory fault injector. Configuration changes take effect without restarting containers and are safe under concurrent requests. The debug API is intended only for this local experiment; it has no authentication and must not be exposed as a production control plane.

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

Development endpoints on Orders (`:8081`) and Payment (`:8082`):

| Endpoint | Purpose |
| --- | --- |
| `GET /debug/fault` | Read current configuration |
| `POST /debug/fault` | Replace configuration with a strict JSON object |
| `POST /debug/reset` | Restore `{ "latency_ms": 0, "error_rate": 0 }` |

Unknown JSON fields and invalid values return `400`; a non-JSON update returns `415`. Faults affect only `/orders/current` and `/payments/authorize`. Health and debug endpoints are never delayed or failed and are excluded from tracing.

Convenient demo commands:

```bash
make fault-status
make fault-payment-latency
make fault-orders-latency
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

## Endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `GET /api/order` | Public endpoint executing the complete chain |
| Gateway | `GET /health` | Liveness check |
| Orders | `GET /orders/current` | Calls Payment and returns the demo order |
| Orders | `GET /health` | Liveness check |
| Payment | `GET /payments/authorize` | Returns the demo authorization result |
| Payment | `GET /health` | Liveness check |
| Orders / Payment | `GET/POST /debug/fault` | Read or replace local fault configuration |
| Orders / Payment | `POST /debug/reset` | Reset local fault configuration |

Unsupported methods on defined endpoints return `405 Method Not Allowed`. A downstream failure is exposed to the caller as `502 Bad Gateway`.

## Local checks

```bash
make fmt
make test
make build
go vet ./...
go test -race ./...
```

The tests cover handlers, downstream failure mapping, fault validation and concurrency, cancellable latency, deterministic error decisions, strict debug JSON, request-ID propagation, the three fault scenarios, W3C TraceContext and Baggage propagation, and the complete parent-child span hierarchy through the in-process service chain. Tests do not require an external Collector.

## Configuration

| Variable | Service | Default outside Docker |
| --- | --- | --- |
| `HTTP_ADDR` | all | `:8080`, `:8081`, or `:8082` |
| `ORDERS_URL` | Gateway | `http://orders:8081` |
| `PAYMENT_URL` | Orders | `http://payment:8082` |
| `HTTP_CLIENT_TIMEOUT` | Gateway / Orders | `3s` / `2s` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | `localhost:4317` |
| `OTEL_EXPORTER_OTLP_INSECURE` | all | `true` |

Compose sets the OTLP endpoint to `otel-collector:4317`. The `service.name` resource attribute is fixed in each binary as `gateway`, `orders`, or `payment`.

Host ports default to:

- Gateway: `18080`;
- Orders: `8081`;
- Payment: `8082`;
- Jaeger UI: `16686`.

They can be overridden with `GATEWAY_PORT`, `ORDERS_PORT`, `PAYMENT_PORT`, and `JAEGER_UI_PORT` without changing container-to-container addresses.

## Pinned observability components

- OpenTelemetry Go API, SDK, and OTLP trace exporter: `v1.45.0`;
- OpenTelemetry HTTP instrumentation: `v0.70.0`;
- OpenTelemetry Collector Contrib: `0.158.0`;
- Jaeger v2: `2.20.0`.
