# M13 Final-Test Reservation

Status: **RESERVED_FINAL_TEST**

- System: OpenTelemetry Astronomy Shop.
- Source: <https://github.com/open-telemetry/opentelemetry-demo>
- Audited commit: `8c47d47c9ac27710d2b2a153bcd53e483bffe66d`
- License: Apache-2.0.
- Expected services: at least the core frontend, frontend-proxy, product
  catalog, cart, checkout, payment, currency, shipping, recommendation and ad
  services, plus telemetry infrastructure.
- Deployment feasibility: official modular Docker Compose definitions.
- Telemetry feasibility: native OTLP traces/metrics through the OpenTelemetry
  Collector with an optional Jaeger/Prometheus layer.

M13 does not clone, deploy, inject faults into, generate labeled incidents for,
or run RCA against this system. It is reserved for the one-time post-M13 locked
transfer evaluation.
