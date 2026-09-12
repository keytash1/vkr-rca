# M13 Development-System Audit

Audit completed before any M13 RCA prediction. Selection used deployment,
telemetry, workload, fault-injection and licensing feasibility only.

## Candidate 1 — DeathStarBench Social Network — selected

- Source: <https://github.com/delimitrou/DeathStarBench/tree/master/socialNetwork>
- Commit: `6ecb09706140f8730b5385c08f1386c654c3c526`
- License: Apache-2.0 at repository root.
- Runtime: C++ Thrift services, OpenResty/Lua gateway, MongoDB, Redis,
  Memcached and Jaeger.
- Observable application graph: an HTTP gateway plus eleven Thrift services;
  compose-post provides a fan-out path suitable for local-vs-propagated symptom
  analysis.
- Workload: upstream compose-post and timeline workloads; M13 uses a
  deterministic HTTP generator because upstream wrk2 explicitly excludes ARM.
- Telemetry: Jaeger spans are emitted by the gateway and services; Docker API
  metrics provide CPU, memory, network and traffic at one-second cadence.
- Injection: service-scoped CPU and memory processes, network-namespace netem,
  and Docker pause.
- Deployment: upstream application image pinned by digest
  `sha256:a845266e98ce15d204ee7b98d41a2a95820af525013ce70f14104f5b9b5e92b6`.
  It is amd64 and runs under Docker emulation on the ARM64 host; this constraint
  must pass canaries before corpus acceptance.

Selection reason: strongest combination of trace fan-out, meaningful
propagation, more than six independently faultable services and manageable
single-host Compose adaptation.

## Candidate 2 — DeathStarBench Media Microservices — not selected

- Source: <https://github.com/delimitrou/DeathStarBench/tree/master/mediaMicroservices>
- Commit/license: same pinned DeathStarBench commit and Apache-2.0 license.
- Runtime/telemetry: C++ Thrift, OpenResty, MongoDB, Redis, Memcached and Jaeger.
- Deployment: 33 upstream containers and substantial movie/user initialization.
- Reason: valid but more expensive than Social Network on the 2 CPU/8 GiB host;
  it adds no benchmark-family independence and is not consumed.

## Candidate 3 — OpenTelemetry Astronomy Shop — reserved

- Source: <https://github.com/open-telemetry/opentelemetry-demo>
- Audited commit: `8c47d47c9ac27710d2b2a153bcd53e483bffe66d`
- License: Apache-2.0.
- Runtime: polyglot microservices with Docker Compose, an OpenTelemetry
  Collector and optional Jaeger/Prometheus observability layer.
- Feasibility: more than six observable services, built-in OTLP tracing,
  deterministic load generator and service-scoped container faults.
- Status: `RESERVED_FINAL_TEST`; not cloned, deployed, faulted or scored in M13.
