# RCA for distributed services

Milestone 2 of the RCA graduation project: a synchronous Go service chain with end-to-end OpenTelemetry tracing.

```text
Client -> Gateway -> Orders -> Payment
              \         |         /
               OTLP/gRPC spans
                     |
              OTel Collector -> Jaeger
```

One request creates a single distributed trace containing the server and client spans for all three services. Fault injection, anomaly detection, service-graph reconstruction, and RCA logic are intentionally deferred to later milestones.

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

## Endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `GET /api/order` | Public endpoint executing the complete chain |
| Gateway | `GET /health` | Liveness check |
| Orders | `GET /orders/current` | Calls Payment and returns the demo order |
| Orders | `GET /health` | Liveness check |
| Payment | `GET /payments/authorize` | Returns the demo authorization result |
| Payment | `GET /health` | Liveness check |

Unsupported methods on defined endpoints return `405 Method Not Allowed`. A downstream failure is exposed to the caller as `502 Bad Gateway`.

## Local checks

```bash
make fmt
make test
make build
go vet ./...
go test -race ./...
```

The tests cover handlers, downstream failure mapping, configuration validation, request-ID propagation, W3C TraceContext and Baggage propagation, and the complete parent-child span hierarchy through the in-process service chain. Tests do not require an external Collector.

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
