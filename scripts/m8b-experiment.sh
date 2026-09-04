#!/bin/sh
set -eu

python_bin="${ML_PYTHON:-.venv/bin/python}"
binary="${M8B_BINARY:-/tmp/vkr-rca-m8b-offline-rca}"
if test -n "${M8B_LIMIT:-}"; then
    data_dir="${M8B_DATA_DIR:-external-data/rcaeval-smoke}"
    artifact_dir="${M8B_ARTIFACT_DIR:-artifacts/m8b/smoke-v1}"
else
    data_dir="${M8B_DATA_DIR:-external-data/rcaeval}"
    artifact_dir="${M8B_ARTIFACT_DIR:-artifacts/m8b/m8b-external-v1}"
fi

test -x "$python_bin" || { echo "run 'make ml-setup' first" >&2; exit 1; }
go build -o "$binary" ./cmd/offline-rca

set -- --data-dir "$data_dir" --artifact-dir "$artifact_dir" --binary "$binary"
if test -n "${M8B_LIMIT:-}"; then
    set -- "$@" --limit "$M8B_LIMIT"
fi
PYTHONPATH=ml "$python_bin" -m rca_ml.m8b_experiment "$@"
if test -z "${M8B_LIMIT:-}"; then
    rcaeval_source="${M8B_RCAEVAL_SOURCE:-external-data/RCAEval-source}"
    if ! test -d "$rcaeval_source/.git"; then
        git clone https://github.com/phamquiluan/RCAEval.git "$rcaeval_source"
    fi
    git -C "$rcaeval_source" checkout --detach 405c8fd24071af41ceb4b3aabb451e5e3e15d6c6
    PYTHONPATH="ml:$rcaeval_source" "$python_bin" -m rca_ml.m8b_official_baselines \
        --rcaeval-source "$rcaeval_source" --data-dir "$data_dir" \
        --output "$artifact_dir/official-baselines.json"
    PYTHONPATH=ml "$python_bin" -m rca_ml.m8b_finalize --artifact-dir "$artifact_dir"
fi
