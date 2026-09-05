#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=ml .venv/bin/python -m rca_ml.m10c_features
PYTHONPATH=ml .venv/bin/python -m rca_ml.m10c_candidate_audit
PYTHONPATH=ml .venv/bin/python -m rca_ml.m10c_experiment

