"""Frozen M13 inference on a pre-fitted unseen-system adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import xgboost as xgb

from .m12_adapter import canonical_features
from .m12_evaluate import rank_candidates
from .m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from .m13_protocol import deterministic_chance, rank_scores
from .m13_runtime import M13Runtime


class FrozenM13TransferRuntime:
    """Apply byte-frozen M13 models to target-specific healthy expectations."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        model_dir = self.root / "ml/models/m14"
        self.freeze = json.loads((self.root / "ml/models/m13/freeze-manifest.json").read_text())
        self.baseline = json.loads((model_dir / "healthy-baseline.json").read_text())
        self.legacy_baseline = json.loads((model_dir / "legacy-metric-baseline.json").read_text())
        self.services = tuple(json.loads((self.root / "deploy/m14/config.json").read_text())["candidate_services"])
        self.columns = tuple(self.freeze["feature_schema"])
        if self.columns != tuple(FEATURES + RANKING_FEATURES):
            raise RuntimeError("frozen M13 feature schema drift")
        self.models = []
        for name, expected_hash in sorted(self.freeze["models"].items()):
            path = self.root / "ml/models/m13" / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise RuntimeError(f"frozen M13 model hash mismatch: {name}")
            model = xgb.Booster(); model.load_model(path); self.models.append(model)
        if len(self.models) != 5:
            raise RuntimeError("frozen M13 ensemble is incomplete")

    def rank_all(self, incident: dict) -> dict[str, list[dict]]:
        incident_id = str(incident.get("incident_id", "m14-window"))
        if tuple(incident.get("candidate_services", ())) != self.services:
            raise RuntimeError("M14 candidate universe drift")
        clean = {key: value for key, value in incident.items() if key not in {"incident_id", "candidate_services", "workload_result"}}
        rows = build_candidate_rows(clean, self.baseline, self.services)
        legacy_rows = canonical_features(clean["metrics"], self.legacy_baseline, self.services, self.baseline["expected_edges"])
        frozen_m11 = rank_candidates(incident_id, legacy_rows, self.root)["m11_top5"]
        M13Runtime._add_ranking_context(rows, frozen_m11)
        matrix = np.asarray([[row["features"][name] for name in self.columns] for row in rows], dtype=np.float32)
        data = xgb.DMatrix(matrix, feature_names=list(self.columns))
        scores = np.mean([model.predict(data) for model in self.models], axis=0)
        m13 = rank_scores({row["service"]: float(score) for row, score in zip(rows, scores, strict=True)})
        return {
            "chance": deterministic_chance(incident_id, self.services, seed=20260912),
            "metric_heuristic": rank_scores({row["service"]: float(row["features"]["metric_max_shift"]) for row in rows}),
            "frozen_m11": frozen_m11,
            "frozen_m13": m13,
        }
