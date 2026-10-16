"""Adapt the sealed transfer runtime to a configured service profile.

The experimental M14 runtime and its recorded checksum remain unchanged.
Only the healthy expectations and candidate universe vary by installation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import xgboost as xgb

from rca_ml.m14_runtime import FrozenM13TransferRuntime
from rca_ml.m13_features import FEATURES, RANKING_FEATURES


class ProfileTransferRuntime(FrozenM13TransferRuntime):
    def __init__(self, root: Path, artifact_dir: Path, services: tuple[str, ...]):
        # Reuse the sealed rank_all algorithm, but do not load the M14 test
        # system's baseline or service list. A product installation must not
        # depend on the independent evaluation corpus.
        self.root = root.resolve()
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
        baseline = json.loads((artifact_dir / "healthy-baseline.json").read_text())
        legacy = json.loads((artifact_dir / "legacy-metric-baseline.json").read_text())
        if set(baseline["metric"]) != set(candidates) or set(baseline["trace"]) != set(candidates):
            raise ValueError("healthy baseline and candidate universe differ")
        self.baseline = baseline
        self.legacy_baseline = legacy
        self.services = candidates
