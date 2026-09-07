# M12 Generic Adapter Contract

The inference boundary accepts only an opaque incident ID, time-window metric
records, metadata-derived candidate service IDs, and directed deployment edges.
Root service, fault family, dataset/system name and labels are rejected. Service
identity is used only to join samples and ranking output; it is never encoded as
a numeric feature.

| Canonical family | Source | Raw type | Transformation | Aggregation/unit | Missing semantics |
|---|---|---|---|---|---|
| CPU | Docker stats CPU deltas | counter deltas | normalized by system CPU delta | per-container CPU cores | family unavailable |
| memory | Docker stats usage minus inactive file cache | gauge | none | per-container bytes | family unavailable |
| network | receive + transmit byte counters | counter | 5 s rate | per-container bytes/s | family unavailable |
| traffic_rate | receive byte counter | counter | 5 s rate | per-container bytes/s | family unavailable |

The Docker API exporter publishes container values and counters to Prometheus,
which returns real one-second observations. Rate windows do not create
synthetic points. Latency, error rate, disk, saturation, dependency, runtime,
database, cache and queue families are left missing because cAdvisor does not
provide defensible service-level semantics for them.

Healthy values fit per-service median/IQR statistics. Incident values become
absolute robust shifts and persistence. The frozen M10C schema receives only
its pre-existing generic availability, CPU percentile, topology and coverage
features; unexposed fields remain zero. Deployment edges produce degree and
reachability ratios. Trace features are zero through the already-defined
missing-modality path.

The four interfaces are `MetricSource`, `TraceSource`, `TopologySource` and
`IncidentSource`. The current live collector implements metrics and deployment
topology. Jaeger receives spans from all eight services, but no new M12-specific
trace-to-feature mapping is introduced after freeze; inference therefore uses
the frozen missing-trace behavior. The shadow API is
`POST /incidents/analyze` and returns rankings, raw model scores, coverage and
limitations—never probability or causal verification.
