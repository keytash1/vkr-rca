"""Offline CLI for ranking all READY services from an M6 feature snapshot."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import feature_rows
from .schema import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, MODEL_VERSION


def predict_snapshot(model: xgb.Booster, snapshot: dict) -> dict:
    candidates = feature_rows(snapshot)
    if not candidates:
        return {"model_version": MODEL_VERSION, "feature_schema": FEATURE_SCHEMA_VERSION, "ranking": []}
    matrix = np.asarray([[values[column] for column in FEATURE_COLUMNS] for _, values in candidates], dtype=np.float32)
    data = xgb.DMatrix(matrix, feature_names=list(FEATURE_COLUMNS))
    scores = model.predict(data)
    ranking = [
        {"service": service, "ml_score": float(score)}
        for (service, _), score in zip(candidates, scores, strict=True)
    ]
    ranking.sort(key=lambda item: (-item["ml_score"], item["service"]))
    for index, item in enumerate(ranking, 1):
        item["rank"] = index
    return {"model_version": MODEL_VERSION, "feature_schema": FEATURE_SCHEMA_VERSION, "ranking": ranking}


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--features-file", type=Path)
    source.add_argument("--features-url")
    parser.add_argument("--model", type=Path, default=Path("ml/models/m7-lambdamart-v1/model.json"))
    args = parser.parse_args()
    if args.features_file:
        snapshot = json.loads(args.features_file.read_text(encoding="utf-8"))
        if "feature_snapshot" in snapshot:
            snapshot = snapshot["feature_snapshot"]
    else:
        with urllib.request.urlopen(args.features_url, timeout=10) as response:
            snapshot = json.load(response)
    model = xgb.Booster()
    model.load_model(args.model)
    print(json.dumps(predict_snapshot(model, snapshot), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
