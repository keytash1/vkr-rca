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

The first build attempt also observed transient Debian mirror `404` responses
while building the ancillary `flagd-ui`. A clean retry resolved those responses;
no image or source substitution was made for that component.
