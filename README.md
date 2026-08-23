# RCA for distributed services

Milestone 1 of the RCA graduation project: a minimal synchronous service chain written in Go.

```text
Client -> Gateway (:8080) -> Orders (:8081) -> Payment (:8082)
```

This milestone deliberately contains no OpenTelemetry, fault injection, anomaly detection, or RCA logic. Those belong to later milestones after the HTTP chain is proven.

## Requirements

- Docker with Docker Compose
- `curl` for the manual smoke request
- Go 1.26 only for running outside Docker

## Run

Build the images, start the services, and wait for their health checks:

```bash
docker compose up --build -d --wait
```

Call the public Gateway endpoint:

```bash
curl --fail --silent --show-error \
  --header 'X-Request-ID: demo-request' \
  http://localhost:18080/api/order
```

Expected response:

```json
{"service":"gateway","order":{"order_id":"demo-order","status":"confirmed","payment":{"provider":"payment","status":"authorized"}}}
```

The same `X-Request-ID` is returned by Gateway, propagated through Orders to Payment, and included in each service's structured JSON request log.

Stop the stack:

```bash
docker compose down --remove-orphans
```

Equivalent shortcuts are available as `make compose-up`, `make smoke`, `make logs`, and `make compose-down`.

The host ports default to `18080`, `8081`, and `8082`. They can be overridden without changing service-to-service addresses. For example, if `18080` is already occupied:

```bash
GATEWAY_PORT=28080 docker compose up --build -d --wait
GATEWAY_PORT=28080 make smoke
```

## Endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `GET /api/order` | Public endpoint executing the complete chain |
| Gateway | `GET /health` | Liveness check |
| Orders | `GET /orders/current` | Calls Payment and returns the demo order |
| Orders | `GET /health` | Liveness check |
| Payment | `GET /payments/authorize` | Returns the demo authorization result |
| Payment | `GET /health` | Liveness check |

All other methods on defined endpoints return `405 Method Not Allowed`. A downstream failure is exposed to the caller as `502 Bad Gateway`.

## Local checks

```bash
make fmt
make test
make build
```

The test suite includes handler tests, downstream failure mapping, configuration validation, request-ID propagation, and an in-process end-to-end chain test.

## Configuration

| Variable | Service | Default |
| --- | --- | --- |
| `HTTP_ADDR` | all | `:8080`, `:8081`, or `:8082` |
| `ORDERS_URL` | Gateway | `http://orders:8081` |
| `PAYMENT_URL` | Orders | `http://payment:8082` |
| `HTTP_CLIENT_TIMEOUT` | Gateway / Orders | `3s` / `2s` |

Compose also accepts `GATEWAY_PORT`, `ORDERS_PORT`, and `PAYMENT_PORT` for overriding the corresponding host ports.
