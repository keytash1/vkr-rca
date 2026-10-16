# Runtime-only image. Build from the repository root; no source instrumentation,
# injected faults, research datasets, baseline of a test system, or Docker API.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS dependencies
WORKDIR /build
COPY deploy/product/requirements.txt requirements.txt
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rca && useradd --uid 10001 --gid rca --no-create-home rca
COPY --from=dependencies /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* && rm -r /wheels
WORKDIR /opt/rca
COPY ml/rca_ml/__init__.py ml/rca_ml/schema.py ml/rca_ml/m10c_schema.py \
     ml/rca_ml/m10d_reranker.py ml/rca_ml/m11_protocol.py ml/rca_ml/m12_adapter.py \
     ml/rca_ml/m13_features.py ml/rca_ml/m13_protocol.py ml/rca_ml/m13_trace.py ml/rca_ml/
COPY ml/models/m10c-v2/feature-schema.json ml/models/m10c-v2/m10c-core-v2.json ml/models/m10c-v2/
COPY ml/models/m11/candidate-recovery-k5-seed-*.json ml/models/m11/
COPY ml/models/m12/ood-stats.json ml/models/m12/
COPY ml/models/m13/freeze-manifest.json ml/models/m13/diagnostic-ranker-seed-*.json ml/models/m13/
COPY cmd/thesis_demo/server.py cmd/thesis_demo/live_sources.py cmd/thesis_demo/profile_runtime.py \
     cmd/thesis_demo/runtime_assets.py cmd/thesis_demo/api_contract.py cmd/thesis_demo/api_errors.py \
     cmd/thesis_demo/profile_check.py cmd/thesis_demo/profile_setup.py cmd/thesis_demo/
COPY cmd/thesis_demo/static/ cmd/thesis_demo/static/
RUN mkdir -p deploy/profiles
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/rca/ml
USER 10001:10001
EXPOSE 18100
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:18100/api/health', timeout=4).read()"
# Binding is inside an isolated container. Publish ONLY to a host loopback port,
# or place behind an independently secured reverse proxy, as documented.
CMD ["python", "cmd/thesis_demo/server.py", "--root", "/opt/rca", "--host", "0.0.0.0", "--unsafe-public", "--port", "18100"]
