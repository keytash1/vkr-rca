#!/bin/sh
set -eu

python_bin="${ML_PYTHON:-.venv/bin/python}"
jaeger_port="${JAEGER_UI_PORT:-16686}"
run_id="${M7_RUN_ID:-m7-$(date -u +%Y%m%dT%H%M%SZ)-seed-20260904}"

cleanup() {
	JAEGER_UI_PORT="$jaeger_port" docker compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

JAEGER_UI_PORT="$jaeger_port" docker compose up --build -d --wait
PYTHONPATH=ml "$python_bin" -m rca_ml.experiment \
	--run-id "$run_id" \
	--seed 20260904 \
	--incidents-per-pair 100 \
	--healthy-controls 60 \
	--baseline-requests 100 \
	--requests-per-incident 20 \
	--concurrency 20 \
	--live
