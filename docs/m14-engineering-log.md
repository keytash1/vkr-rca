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
