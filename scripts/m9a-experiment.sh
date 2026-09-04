#!/bin/sh
set -eu

python_bin="${ML_PYTHON:-.venv/bin/python}"
test -x "$python_bin" || { echo "run 'make ml-setup' first" >&2; exit 1; }

set -- --data-dir "${M9A_DATA_DIR:-external-data/rcaeval}" \
    --m8b-artifacts "${M9A_M8B_ARTIFACTS:-artifacts/m8b/m8b-external-v1}" \
    --artifact-dir "${M9A_ARTIFACT_DIR:-artifacts/m9a/m9a-external-v1}" \
    --model-dir "${M9A_MODEL_DIR:-ml/models/m9a-detector-v2}"
if test -n "${M9A_SYNTHETIC_ONLY:-}"; then
    set -- "$@" --synthetic-only
fi
PYTHONPATH=ml "$python_bin" -m rca_ml.m9a_experiment "$@"
