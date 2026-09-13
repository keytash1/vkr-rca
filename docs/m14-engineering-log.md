# M14 Engineering Reproducibility Log

This log records deployment-only events. It does not alter the locked corpus,
features, models, comparators, metrics, statistics or verdict gates.

## 2026-09-13: historical QuoteService dependency resolution

The audited upstream checkout at
`8c47d47c9ac27710d2b2a153bcd53e483bffe66d` pins `react/http v1.11.0` in
`src/quote/composer.json` and contains no `composer.lock`. At experiment build
time, the pinned Composer 2.10.3 image refused to resolve that exact upstream
constraint because its mutable security-advisory feed had begun blocking it.

M14 therefore uses `deploy/m14/Dockerfile.quote-repro`, which is a line-for-line
copy of the upstream QuoteService Dockerfile with one build-only command before
`composer install`: `composer config --global audit.block-insecure false`.
Application source files, the upstream dependency constraint, runtime image and
instrumentation remain unchanged. The shim prevents a time-varying advisory
policy from making the historical source commit unbuildable; it neither changes
the RCA method nor uses predictions or truth.

The first build attempt also observed Debian mirror `404` responses while
building the ancillary `flagd-ui`. Later attempts reached the updated index but
repeatedly timed out downloading it, including with Compose parallelism limited
to two. Independent Gradle and PECL fetches also suffered DNS timeouts.

To keep this infrastructure failure outside the measured candidate universe,
the non-candidate `image-provider` is run from the official pinned Astronomy
Shop `3.0.0` image. Its image digest was recorded by Docker. The three support
processes that the experiment never queries (`flagd-ui`, `telemetry-docs`, and
the disabled upstream `load-generator`) are deterministic inert containers
using `alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc`.
The first two retain successful health checks solely to satisfy the upstream
frontend-proxy dependencies; M14 uses its own locked workload generator.

Their Compose `build` definitions are explicitly reset. The 12 RCA candidate
services remain source-built from the audited exact checkout (with the
documented QuoteService shim), while the real `flagd` feature-flag service is
unchanged. This substitution happened before readiness, healthy baseline,
fault injection, prediction, or truth opening and was not informed by RCA
output.

## 2026-09-13: AdService Gradle transport tolerance

The upstream Gradle wrapper properties set `networkTimeout=10000` and
`retries=0`. Three exact-source builds failed while downloading the unchanged
Gradle 9.7.1 distribution because the experiment host exceeded that ten-second
read timeout. `deploy/m14/Dockerfile.ad-repro` copies the upstream Dockerfile
and changes only the builder-image wrapper transport settings to a 300-second
timeout and five retries. The Gradle URL, checksums, dependencies, source,
runtime image, Java agent and application configuration are unchanged. This
shim was committed before readiness or data collection.

The same build then exposed an HTTP/2 protocol error in Dockerfile `ADD` while
fetching the upstream-pinned OpenTelemetry Java agent. The shim downloads the
identical versioned URL with the JDK builder's `wget` using ten retries and a
300-second timeout, then copies the resulting jar into the same runtime path.
This changes download transport only; the agent version remains the upstream
`OTEL_JAVA_AGENT_VERSION` build argument.

## Resumption after host disk exhaustion

The host ran out of disk space during CheckoutService dependency download.
The user rebooted and freed space; resumption confirmed 110 GiB free and
readable Docker storage. The tagged AdService and CartService images survived.
No baseline, canary, corpus or predictions existed at this point.

Pre-collection harness review tightened healthy workload validation to reject
all non-2xx responses (previously HTTP 4xx could pass). CPU/memory fault-agent
compilation and copying now occur before the observation window so setup does
not consume the locked 30-second workload period. These corrections precede
all experiment data and do not change the models or planned fault intensities.

The pre-collection review also moved healthy-only baseline fitting to the end
of healthy collection, before fault injection. Sealing checks that these fitted
artifacts still match the healthy telemetry. Scoring and opening now verify
the hashes of all Python inference dependencies, comparator models, feature
schema, OOD statistics and collection code, not only the M13 ensemble.
Deployment deviations are explicitly carried into healthy data metadata.

The frontend proxy host ports replace (rather than extend) upstream bindings,
avoiding a collision with another local project on port 8080. Experiment HTTP
endpoints bind to loopback, and its bridge network has a project-specific name.
The official image-provider image is pinned by its inspected digest.

Exporter review removed stale-value replay when one container's Docker stats
request fails: successful containers replace the snapshot while the failed
container is absent, rather than freezing all 12 previous values. A snapshot
older than ten seconds produces HTTP 503, and a timestamp gauge makes sampling
freshness observable. Missing telemetry remains missing; it is not imputed.

Early infrastructure startup found that the M14 collector command override
had omitted the upstream `service.profilesSupport` feature gate while retaining
the upstream profiles pipeline. Restoring the exact upstream flag fixes that
configuration error; no signal mapping or application instrumentation changes.

Upstream random host-port publications for internal application/database
services are removed in the experiment overlay. Those services still use the
same container ports and DNS names on the private bridge; only the four
explicit loopback publications (frontend, Envoy admin, Jaeger, Prometheus)
remain reachable from the host. This confines the historically pinned demo
dependencies to a local experiment rather than exposing them on the LAN.

Readiness records Docker CPU/RAM resources, Compose state and co-resident
running containers without copying environment secrets. This evidence and all
M14 deployment files are hashed in the experiment seal.

The trace exporter overlay also retains the upstream `span_metrics` connector:
the inherited metrics pipeline consumes that connector and cannot start when
its trace-side producer is missing. Jaeger is added alongside it, rather than
disconnecting the original pipeline.

## Full mixed-workload smoke gate

All 12 application images were successfully source-built and started. Initial
individual product/recommendation/ad/cart requests returned HTTP 200, and
native traces and Docker metrics reached their respective adapters.

The first 20-second mixed smoke run at the locked six operations per second
returned 77 HTTP 200, 16 HTTP 500 and 27 timeouts. PostgreSQL restarted during
the run. Docker's current `OOMKilled` state was false after restart, but the
VM kernel log confirmed a memory-cgroup OOM for the exact `astronomy-db`
container ID (`d0725f5a44ba177601ab2bc2cea397ecd4b89efbd23741dc9d705a7265d2d411`)
with the inherited 80 MiB limit. ProductCatalog maps database-read errors to
`NOT_FOUND`, explaining misleading product-not-found frontend messages.
An unchanged second smoke run improved to 118 HTTP 200 and two timeouts, which
still does not pass the healthy gate.

Before any baseline or fault data, the non-candidate PostgreSQL support service
receives a 512 MiB limit. Application candidates, fault magnitudes, request mix
and rate, model features and verdict gates are unchanged. The deployment
exception is included in the raw healthy metadata and frozen Compose hash.

Readiness environment capture was also corrected to filter the formatted
container inventory locally: this Docker version rejects the negative label
filter used in the original command. No environment secrets are recorded.

The mixed smoke run also demonstrated that request completion can lag the
dispatch interval. Before fault collection, the harness was corrected to end
the incident observation and reset network/pause faults at `start + 30s`, not
after all slow HTTP futures finish. It then drains requests and collects the
fixed window. A regression test simulates an eight-second late completion and
verifies the unchanged 30-second window. Corpus duration overrides are rejected.

The next 30-second smoke run returned 179 HTTP 200 and one timeout. A subsequent
60-second diagnostic run (same six operations/second and seed) returned 170
HTTP 200 and 190 timeouts: ad and cart were 72/72 successful each; product,
recommendation and checkout were 14/72, 5/72 and 7/72 respectively. PostgreSQL
had no new restart or blocked queries. During the run ProductCatalog consumed
55.95% CPU at 18.33 MiB of its 20 MiB cgroup limit; its inherited Go soft limit
was 16 MiB. Payment was at 135.1 MiB of 140 MiB and 51.86% CPU. These observations
support resource-pressure investigation, not an RCA model result.

Before any healthy baseline or fault injection, M14 adopts a uniform 512 MiB
memory ceiling for all 12 application candidates and a 384 MiB Go soft limit
for Checkout and ProductCatalog. This is a fixed deployment envelope, not
per-root ranking optimization. It provides headroom for application runtime,
instrumentation, health checks and the unchanged 32 MiB injection agent. Actual
memory is allocated on demand; these are limits, not 6 GiB of reservations.
The source images, instrumentation, CPU allocation, workload, faults and frozen
RCA method remain unchanged. Subsequent healthy validation must pass before
this configuration can enter the sealed experiment.

The first 60-second smoke after this profile returned 356 HTTP 200 and four
timeouts (360 operations); it is not accepted as healthy data. The locked
300-second warm-up gate must pass without any non-2xx responses before the
harness can start the 900-second baseline. Progress messages expose those
phase boundaries without exposing or generating rankings.

## Accepted healthy baseline and canary compatibility

The locked 300-second warm-up completed 1,800/1,800 operations with HTTP 200.
The subsequent 900-second baseline completed 5,400/5,400 operations with HTTP
200 (1,080 for each operation). It contains 43,248 metric samples covering all
48 candidate/family pairs and 123,218 canonical native spans, including all
12 candidates. Its SHA-256 is
`9b96041ada41a356cf6ac5e3b8bae13765530449212954946c62636cbdff631e`.
Both healthy-only baseline artifacts were fitted before any injection.

The first canary stopped during CPU process-state inspection: this Docker
daemon rejects `docker top ... -eo args` with "Couldn't find PID field in ps
output". Adding the required PID column (`-eo pid,args`) fixes inspection,
without changing the agent, fault intensity or validity criterion. The agent
self-expires after 30 seconds. No corpus incident or ranking was produced by
this aborted canary. The full five-mechanism canary is rerun after this fix.
