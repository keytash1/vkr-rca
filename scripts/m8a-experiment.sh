#!/bin/sh
set -eu

python_bin="${ML_PYTHON:-.venv/bin/python}"
seed="${M8A_SEED:-20260904}"
run_b="${M8A_B_RUN_ID:-m8a-b-full-seed-${seed}}"
run_c="${M8A_C_RUN_ID:-m8a-c-full-seed-${seed}}"
dataset_a="${M8A_A_DATASET:-artifacts/m7/m7-full-seed-20260904}"
dataset_b="artifacts/m8a/${run_b}"
dataset_c="artifacts/m8a/${run_c}"
compose_b="deploy/m8a/topology-b.compose.yml"
compose_c="deploy/m8a/topology-c.compose.yml"

cleanup() {
	docker compose -p vkr-rca-m8a-b -f "$compose_b" down --remove-orphans >/dev/null 2>&1 || true
	docker compose -p vkr-rca-m8a-c -f "$compose_c" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

./scripts/m8a-build-images.sh

docker compose -p vkr-rca-m8a-b -f "$compose_b" up -d --wait
PYTHONPATH=ml "$python_bin" -m rca_ml.m8a_generate \
	--topology deploy/m8a/topology-b.json \
	--output-dir "$dataset_b" \
	--seed "$seed" \
	--incidents-per-pair 50 \
	--healthy-controls 50 \
	--baseline-requests 100 \
	--requests-per-incident 20 \
	--concurrency 20 \
	--temporal-repetitions 1 \
	--stability-scenarios 10 \
	--stability-repetitions 5
docker compose -p vkr-rca-m8a-b -f "$compose_b" down --remove-orphans

docker compose -p vkr-rca-m8a-c -f "$compose_c" up -d --wait
PYTHONPATH=ml "$python_bin" -m rca_ml.m8a_generate \
	--topology deploy/m8a/topology-c.json \
	--output-dir "$dataset_c" \
	--seed "$seed" \
	--incidents-per-pair 50 \
	--healthy-controls 50 \
	--baseline-requests 100 \
	--requests-per-incident 20 \
	--concurrency 20 \
	--temporal-repetitions 1 \
	--stability-scenarios 10 \
	--stability-repetitions 5
docker compose -p vkr-rca-m8a-c -f "$compose_c" down --remove-orphans

PYTHONPATH=ml "$python_bin" -m rca_ml.m8a_experiment \
	--topology-a-dataset "$dataset_a" \
	--topology-b-dataset "$dataset_b" \
	--topology-c-dataset "$dataset_c" \
	--seed "$seed"
