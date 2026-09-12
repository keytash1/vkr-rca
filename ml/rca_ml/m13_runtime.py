"""Frozen, truth-free runtime interface for the promoted M13 diagnostic ranker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import xgboost as xgb

from .m12_adapter import canonical_features
from .m12_evaluate import rank_candidates
from .m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from .m13_protocol import rank_scores


class M13Runtime:
    """Turn one canonical incident window into ranked, non-causal evidence."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        model_dir = self.root / "ml/models/m13"
        self.freeze = json.loads((model_dir / "freeze-manifest.json").read_text())
        self.baseline = json.loads((model_dir / "healthy-baseline.json").read_text())
        self.legacy_baseline = json.loads((model_dir / "legacy-metric-baseline.json").read_text())
        self.services = json.loads((model_dir / "system-manifest.json").read_text())["candidate_services"]
        self.columns = tuple(self.freeze["feature_schema"])
        if self.columns != tuple(FEATURES + RANKING_FEATURES):
            raise RuntimeError("frozen M13 feature schema does not match runtime")
        self.models = []
        for name, expected_hash in sorted(self.freeze["models"].items()):
            path = model_dir / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise RuntimeError(f"M13 model hash mismatch: {name}")
            model = xgb.Booster()
            model.load_model(path)
            self.models.append(model)
        if len(self.models) != 5:
            raise RuntimeError("M13 five-seed ensemble is incomplete")

    def health(self) -> dict:
        return {"status": "ok", "models": len(self.models), "architecture": self.freeze["selected_architecture"]}

    def analyze(self, incident: dict) -> dict:
        incident_id = str(incident.get("incident_id", "runtime-window"))
        clean = {key: value for key, value in incident.items() if key != "incident_id"}
        rows = build_candidate_rows(clean, self.baseline, self.services)
        legacy_rows = canonical_features(clean["metrics"], self.legacy_baseline, self.services, self.baseline["expected_edges"])
        frozen_m11 = rank_candidates(incident_id, legacy_rows, self.root)["m11_top5"]
        self._add_ranking_context(rows, frozen_m11)
        matrix = np.asarray([[row["features"][name] for name in self.columns] for row in rows], dtype=np.float32)
        data = xgb.DMatrix(matrix, feature_names=list(self.columns))
        scores = np.mean([model.predict(data) for model in self.models], axis=0)
        ranking = rank_scores({row["service"]: float(score) for row, score in zip(rows, scores, strict=True)})
        by_service = {row["service"]: row["features"] for row in rows}
        return {
            "incident_id": incident_id,
            "architecture": self.freeze["selected_architecture"],
            "causal_status": "DIAGNOSTIC_RANKING_ONLY",
            "candidates": [self._evidence(item, by_service[item["service"]]) for item in ranking],
        }

    @staticmethod
    def _add_ranking_context(rows: list[dict], ranking: list[dict]) -> None:
        rank_by_service = {item["service"]: int(item["rank"]) for item in ranking}
        score_by_service = {item["service"]: float(item["score"]) for item in ranking}
        ordered = sorted(score_by_service.values(), reverse=True)
        top, second = ordered[0], ordered[1] if len(ordered) > 1 else ordered[0]
        scale = max(abs(top), 1e-9)
        for row in rows:
            rank = rank_by_service[row["service"]]
            score = score_by_service[row["service"]]
            row["features"].update({
                "base_rank_percentile": 1.0 - (rank - 1) / max(1, len(rows) - 1),
                "base_relative_score": score / scale,
                "base_margin": (top - second) / scale if rank == 1 else (score - top) / scale,
            })

    @staticmethod
    def _evidence(ranked: dict, values: dict) -> dict:
        return {
            "service": ranked["service"], "rank": ranked["rank"], "model_score": ranked["score"],
            "evidence": {
                "metric_support": values["metric_max_shift"],
                "trace_local_support": values["trace_local_support"],
                "propagation_support": max(values["distance_weighted_affected_callers"], values["distance_weighted_affected_callees"]),
                "dependency_wait_support": values["downstream_wait_support"],
                "disappearance_support": values["telemetry_disappearance_score"],
                "coverage": {
                    "metrics": values["metric_coverage"], "traces": values["trace_coverage"],
                    "topology": values["topology_coverage"],
                },
            },
        }
