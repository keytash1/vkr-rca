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
