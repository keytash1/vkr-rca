"""Adapt the sealed transfer runtime to a configured service profile.

The experimental M14 runtime and its recorded checksum remain unchanged.
Only the healthy expectations and candidate universe vary by installation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import xgboost as xgb
import numpy as np

from rca_ml.m13_features import FEATURES, RANKING_FEATURES, build_candidate_rows
from rca_ml.m12_adapter import canonical_features
from rca_ml.m10d_reranker import build_evidence_features, build_reranker_records, predict_ensemble
from rca_ml.m11_protocol import rerank_top_k
from rca_ml.m13_protocol import deterministic_chance, rank_scores
from runtime_assets import EXPECTED_SHA256


class ProfileTransferRuntime:
    def __init__(self, root: Path, artifact_dir: Path, services: tuple[str, ...]):
        # Reuse the sealed rank_all algorithm, but do not load the M14 test
        # system's baseline or service list. A product installation must not
        # depend on the independent evaluation corpus.
        self.root = root.resolve()
        for name, expected in EXPECTED_SHA256.items():
            if hashlib.sha256((self.root / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"runtime artifact checksum differs: {name}")
        model_dir = self.root / "ml/models/m13"
        self.freeze = json.loads((model_dir / "freeze-manifest.json").read_text())
        self.columns = tuple(self.freeze["feature_schema"])
        if self.columns != tuple(FEATURES + RANKING_FEATURES):
            raise RuntimeError("frozen feature schema differs from product runtime")
        self.models = []
        for name, expected_hash in sorted(self.freeze["models"].items()):
            path = model_dir / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise RuntimeError(f"frozen model hash mismatch: {name}")
            model = xgb.Booster()
            model.load_model(path)
            self.models.append(model)
        if len(self.models) != 5:
            raise RuntimeError("frozen ensemble is incomplete")
        candidates = tuple(services)
        if not candidates or candidates != tuple(sorted(set(candidates))):
            raise ValueError("candidate universe must be sorted and unique")
        provenance_path = artifact_dir / "provenance.json"
        if provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text())
            for name, expected in provenance.get("files_sha256", {}).items():
                if name not in {"healthy-baseline.json", "legacy-metric-baseline.json"}:
                    raise ValueError("unexpected baseline artifact in provenance")
                if hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest() != expected:
                    raise ValueError(f"healthy baseline checksum differs: {name}")
        baseline = json.loads((artifact_dir / "healthy-baseline.json").read_text())
        legacy = json.loads((artifact_dir / "legacy-metric-baseline.json").read_text())
        if set(baseline["metric"]) != set(candidates) or set(baseline["trace"]) != set(candidates):
            raise ValueError("healthy baseline and candidate universe differ")
        self.baseline = baseline
        self.legacy_baseline = legacy
        self.services = candidates
        schema = json.loads((self.root / "ml/models/m10c-v2/feature-schema.json").read_text())
        self.context_columns = schema["selected_columns"]
        self.context_model = xgb.Booster()
        self.context_model.load_model(self.root / "ml/models/m10c-v2/m10c-core-v2.json")
        self.recovery_models = []
        for seed in range(20260906, 20260911):
            model = xgb.Booster()
            model.load_model(self.root / f"ml/models/m11/candidate-recovery-k5-seed-{seed}.json")
            self.recovery_models.append(model)
        self.context_stats = json.loads((self.root / "ml/models/m12/ood-stats.json").read_text())["stats"]

    def _context_ranking(self, incident_id: str, rows: list[dict]) -> list[dict]:
        """Exact inference branch used for context, without unused comparators."""
        matrix = np.asarray([[item["vector"][name] for name in self.context_columns] for item in rows], dtype=np.float32)
        scores = self.context_model.predict(xgb.DMatrix(matrix, feature_names=self.context_columns))
        base = sorted(({"service": item["service"], "score": float(score)}
                       for item, score in zip(rows, scores, strict=True)), key=lambda item: (-item["score"], item["service"]))
        for rank, item in enumerate(base, 1):
            item["rank"] = rank
        heuristic = sorted(({"service": item["service"], "score": float(item["metric_max_shift"])} for item in rows),
                           key=lambda item: (-item["score"], item["service"]))
        for rank, item in enumerate(heuristic, 1):
            item["rank"] = rank
        clean_rows = [{"service": item["service"], **item["vector"]} for item in rows]
        profiles = build_evidence_features(clean_rows, base, metric_ranking=heuristic, ood_stats=self.context_stats, top_k=5)
        records = build_reranker_records(incident_id, profiles, base)
        predictions = predict_ensemble(self.recovery_models, records)
        return rerank_top_k({incident_id: base}, predictions, 5)[incident_id]

    @staticmethod
    def _add_context(rows: list[dict], ranking: list[dict]) -> None:
        ranks = {item["service"]: int(item["rank"]) for item in ranking}
        scores = {item["service"]: float(item["score"]) for item in ranking}
        ordered = sorted(scores.values(), reverse=True)
        top, second = ordered[0], ordered[1] if len(ordered) > 1 else ordered[0]
        scale = max(abs(top), 1e-9)
        for row in rows:
            rank, score = ranks[row["service"]], scores[row["service"]]
            row["features"].update({
                "base_rank_percentile": 1.0 - (rank - 1) / max(1, len(rows) - 1),
                "base_relative_score": score / scale,
                "base_margin": (top - second) / scale if rank == 1 else (score - top) / scale,
            })

    def rank_all(self, incident: dict) -> dict[str, list[dict]]:
        incident_id = str(incident.get("incident_id", "runtime-window"))
        if tuple(incident.get("candidate_services", ())) != self.services:
            raise ValueError("candidate universe differs from installed profile")
        clean = {key: value for key, value in incident.items() if key not in {"incident_id", "candidate_services", "workload_result"}}
        rows = build_candidate_rows(clean, self.baseline, self.services)
        metric_rows = canonical_features(clean["metrics"], self.legacy_baseline, self.services, self.baseline["expected_edges"])
        context = self._context_ranking(incident_id, metric_rows)
        self._add_context(rows, context)
        matrix = np.asarray([[row["features"][name] for name in self.columns] for row in rows], dtype=np.float32)
        data = xgb.DMatrix(matrix, feature_names=list(self.columns))
        scores = np.mean([model.predict(data) for model in self.models], axis=0)
        ranking = rank_scores({row["service"]: float(score) for row, score in zip(rows, scores, strict=True)})
        return {"frozen_m13": ranking, "frozen_m11": context,
                "metric_heuristic": rank_scores({row["service"]: float(row["features"]["metric_max_shift"]) for row in rows}),
                "chance": deterministic_chance(incident_id, self.services, seed=20260912)}

    @staticmethod
    def evidence(ranked: dict, values: dict) -> dict:
        return {"service": ranked["service"], "rank": ranked["rank"], "model_score": ranked["score"],
                "evidence": {"metric_support": values["metric_max_shift"], "trace_local_support": values["trace_local_support"],
                             "propagation_support": max(values["distance_weighted_affected_callers"], values["distance_weighted_affected_callees"]),
                             "dependency_wait_support": values["downstream_wait_support"], "disappearance_support": values["telemetry_disappearance_score"],
                             "coverage": {"metrics": values["metric_coverage"], "traces": values["trace_coverage"], "topology": values["topology_coverage"]}}}
