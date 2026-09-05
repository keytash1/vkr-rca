#!/bin/sh
set -eu

python_bin="${ML_PYTHON:-.venv/bin/python}"
binary="${DEMO_OFFLINE_RCA_BINARY:-/tmp/vkr-rca-demo-offline-rca}"

test -x "$python_bin" || { echo "run 'make ml-setup' first" >&2; exit 1; }
GOCACHE="${GOCACHE:-/tmp/vkr-rca-go-build-cache}" go build -o "$binary" ./cmd/offline-rca
PYTHONPATH=ml "$python_bin" -m rca_ml.demo_prepare --binary "$binary"
