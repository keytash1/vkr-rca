#!/bin/sh
set -eu

ML_PYTHON=${ML_PYTHON:-.venv/bin/python}

PYTHONPATH=ml "$ML_PYTHON" -m rca_ml.m9b_experiment --smoke
PYTHONPATH=ml "$ML_PYTHON" -m rca_ml.m9b_experiment
