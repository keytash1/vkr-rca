# M12 Unseen-System Selection

Selection was completed before any M12 RCA prediction or score.

## Selected system

- Project: DeathStarBench Hotel Reservation
- Official source: <https://github.com/delimitrou/DeathStarBench>
- Source commit: `6ecb09706140f8730b5385c08f1386c654c3c526`
- Commit date: `2024-06-27T13:13:08-07:00`
- License: Apache License 2.0 (verified from the pinned repository `LICENSE`)
- Runtime: Go/gRPC services, Consul discovery, MongoDB, Memcached, HTTP frontend
- Upstream deployment: Docker Compose, Kubernetes and OpenShift
- Workload: upstream wrk2 Lua workload plus a deterministic M12 HTTP generator
- Tracing: OpenTracing/Jaeger with configurable sampling

The pinned compose describes ten application services: `frontend`, `profile`,
`search`, `geo`, `rate`, `review`, `attractions`, `recommendation`, `user`, and
`reservation`. The primary mixed workload exercises the eight-service booking
path; review/attractions are retained in the manifest but are not eligible locked
targets unless workload coverage is demonstrated before freeze.

Observed application graph from code/configuration:

```text
frontend -> search -> geo
                  -> rate
frontend -> profile
frontend -> recommendation
frontend -> user
frontend -> reservation
```

Backend MongoDB, Memcached, Consul and Jaeger containers are infrastructure and
are not root candidates in M12.

## Independence and compatibility

Hotel Reservation is neither Online Boutique, Sock Shop nor Train Ticket and is
not a direct derivative of those RCAEval systems. It has more than five
independently identifiable application services, stable request generation,
container/Compose metadata, service-scoped container metrics, and unambiguous
container-targeted fault mechanisms.

Selection did not use the RCA model. Existing Murphy traces are not used as
locked data; all M12 incidents will be generated from this pinned deployment.

## Environment constraints to validate

The host is ARM64 macOS and the active Colima profile has 2 CPUs and 8 GiB RAM.
The experiment uses native source builds where possible and pinned multi-arch
dependencies. Deployment, telemetry cadence and fault canaries must pass before
the locked incident set is generated. Failure of that gate yields an honest
`M12_UNSEEN_VALIDATION: BLOCKED` result.
