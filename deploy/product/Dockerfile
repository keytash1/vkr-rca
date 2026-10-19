# Runtime-only image. Build from the repository root; no source instrumentation,
# injected faults, research datasets, baseline of a test system, or Docker API.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS dependencies
WORKDIR /build
COPY deploy/product/requirements.txt requirements.txt
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rca && useradd --uid 10001 --gid rca --no-create-home rca
COPY --from=dependencies /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* && rm -r /wheels
WORKDIR /opt/rca
COPY deploy/product/LICENSE deploy/product/NOTICE deploy/product/THIRD_PARTY.md deploy/product/THIRD_PARTY_NOTICES ./
COPY ml/rca_ml/__init__.py ml/rca_ml/schema.py ml/rca_ml/m10c_schema.py \
     ml/rca_ml/m10d_reranker.py ml/rca_ml/m11_protocol.py ml/rca_ml/m12_adapter.py \
     ml/rca_ml/m13_features.py ml/rca_ml/m13_protocol.py ml/rca_ml/m13_trace.py ml/rca_ml/
COPY ml/models/m10c-v2/feature-schema.json ml/models/m10c-v2/m10c-core-v2.json ml/models/m10c-v2/
COPY ml/models/m11/candidate-recovery-k5-seed-*.json ml/models/m11/
COPY ml/models/m12/ood-stats.json ml/models/m12/
COPY ml/models/m13/freeze-manifest.json ml/models/m13/diagnostic-ranker-seed-*.json ml/models/m13/
COPY cmd/thesis_demo/server.py cmd/thesis_demo/live_sources.py cmd/thesis_demo/profile_runtime.py \
     cmd/thesis_demo/runtime_assets.py cmd/thesis_demo/api_contract.py cmd/thesis_demo/api_errors.py \
     cmd/thesis_demo/evidence_catalog.py cmd/thesis_demo/assistant_context.py \
     cmd/thesis_demo/trace_adapters.py cmd/thesis_demo/profile_contract.py cmd/thesis_demo/profile_onboarding.py cmd/thesis_demo/analysis_requests.py cmd/thesis_demo/trace_evidence.py cmd/thesis_demo/baseline_applicability.py cmd/thesis_demo/context_source.py cmd/thesis_demo/context_catalog.py \
     cmd/thesis_demo/profile_check.py cmd/thesis_demo/profile_setup.py cmd/thesis_demo/http_observations.py cmd/thesis_demo/
COPY cmd/thesis_demo/static/ cmd/thesis_demo/static/
RUN mkdir -p deploy/profiles
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/rca/ml
USER 10001:10001
EXPOSE 18100
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:18100/healthz', timeout=4).read()"
# Binding is inside an isolated container. Publish ONLY to a host loopback port,
# or place behind an independently secured reverse proxy, as documented.
CMD ["python", "cmd/thesis_demo/server.py", "--root", "/opt/rca", "--host", "0.0.0.0", "--unsafe-public", "--port", "18100"]

# Explicit optional targets. Default final target below stays the minimal runtime.
FROM runtime AS workspace
USER root
# Docker copies this private directory's owner/mode into a new named volume.
# Never repair/chown an existing user's workspace at application startup.
RUN mkdir -p /var/lib/rca-workspace \
    && chown 10001:10001 /var/lib/rca-workspace \
    && chmod 0700 /var/lib/rca-workspace
USER 10001:10001
COPY cmd/thesis_demo/workspace_store.py cmd/thesis_demo/workspace_http.py cmd/thesis_demo/investigations.py \
     cmd/thesis_demo/runbook_corpus.py cmd/thesis_demo/assistant_privacy.py cmd/thesis_demo/assistant_supervisor.py \
     cmd/thesis_demo/assistant_runner.py cmd/thesis_demo/assistant_contract.py cmd/thesis_demo/assistant_budget.py \
     cmd/thesis_demo/assistant_tools.py cmd/thesis_demo/assistant_workflow.py cmd/thesis_demo/

FROM workspace AS assistant
USER root
COPY deploy/product/requirements-assistant.txt /tmp/requirements-assistant.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-assistant.txt
# Public tokenizer data, not account state. Warm explicitly at build time;
# worker preflights never download a vocabulary during an investigation.
ENV TIKTOKEN_CACHE_DIR=/opt/rca/tokenizer-cache
RUN mkdir -p /opt/rca/tokenizer-cache \
    && python -c "import tiktoken,hashlib,pathlib; tiktoken.get_encoding('o200k_base'); p=pathlib.Path('/opt/rca/tokenizer-cache/fb374d419588a4632f3f557e76b4b70aebbca790'); assert hashlib.sha256(p.read_bytes()).hexdigest() == '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'" \
    && chmod -R a=rX /opt/rca/tokenizer-cache
COPY cmd/thesis_demo/assistant_auth.py cmd/thesis_demo/assistant_provider.py cmd/thesis_demo/assistant_worker.py cmd/thesis_demo/
USER 10001:10001

FROM runtime AS default
