# M12 Deployment

M12 deploys the pinned DeathStarBench Hotel Reservation source at commit
`6ecb09706140f8730b5385c08f1386c654c3c526`. The application image is built
locally for the host architecture; all eight application containers use that
same immutable image. MongoDB and Memcached are consolidated into one container
each, while preserving upstream per-service databases and cache keys. This is a
resource adaptation, not an application semantic change.

The stack contains eight application services, Consul, MongoDB, Memcached,
Jaeger, a minimal Docker API metrics exporter and Prometheus. Compose labels
provide service identity. Prometheus scrapes the exporter every second. Raw data stays under ignored
`external-data/m12/`.

```bash
make m12-setup
make m12-up
make m12-healthy
make m12-canary
make m12-run-locked
make m12-freeze
make m12-evaluate
make m12-down
```

The source clone and commit check are automatic. No pre-existing DeathStarBench
installation is required. The local frontend is at `127.0.0.1:15000`,
Prometheus at `127.0.0.1:19090`, Jaeger at `127.0.0.1:16687`, and the optional
shadow endpoint at `127.0.0.1:18120` after `make m12-shadow`.

The deterministic workload uses seed `20260906`, 10 requests/s and four public
frontend routes. The preferred 300-second warm-up and 900-second baseline are
reduced by default to 60 and 180 seconds because the local Colima allocation is
2 CPU/8 GiB and M12 includes 50 live fault runs. The manifest records this
deviation; scrape cadence remains one second and no samples are interpolated.

Faults are container-scoped: `stress-ng` CPU, `stress-ng` memory, `tc netem`
delay, `tc netem` loss and Docker pause. Canaries suppress inference and require
independent mechanism evidence before locked collection may proceed.
