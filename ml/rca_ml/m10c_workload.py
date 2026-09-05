"""Baseline-only robust workload conditioning for M10C telemetry features."""

from __future__ import annotations

import numpy as np

from .m10c_candidates import CanonicalMetric, MetricSource


def robust_linear_fit(x: np.ndarray, y: np.ndarray, iterations: int = 8) -> tuple[float, float]:
    """Small deterministic Huber IRLS fit; no incident-window values are used."""
    design = np.column_stack((np.ones(len(x)), x))
    weights = np.ones(len(x))
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    for _ in range(iterations):
        residual = y - design @ beta
        scale = max(1.4826 * float(np.median(np.abs(residual - np.median(residual)))), 1e-9)
        absolute = np.abs(residual) / (1.345 * scale)
        weights = np.where(absolute <= 1, 1.0, 1.0 / np.maximum(absolute, 1e-12))
        beta = np.linalg.lstsq(design * weights[:, None], y * weights, rcond=None)[0]
    return float(beta[0]), float(beta[1])


def conditioned_residual_features(source: MetricSource, entity: str, inject_unix: int) -> dict[str, float]:
    traffic = source.read_series(entity, "traffic_rate")
    if not traffic:
        return _empty()
    candidates = []
    for workload in traffic:
        for family in source.list_families():
            if family == "traffic_rate":
                continue
            for response in source.read_series(entity, family):
                value = _pair_features(workload, response, inject_unix)
                if value is not None:
                    candidates.append(value)
    if not candidates:
        return _empty()
    candidates.sort(key=lambda value: (-value["workload_residual_peak"], value["source_name"]))
    return {key: float(value) for key, value in candidates[0].items() if key != "source_name"}


def _pair_features(workload: CanonicalMetric, response: CanonicalMetric, inject_unix: int) -> dict | None:
    common, wi, ri = np.intersect1d(workload.timestamps, response.timestamps, return_indices=True)
    if len(common) < 40:
        return None
    x = workload.values[wi].astype(float)
    y = response.values[ri].astype(float)
    baseline = (common >= inject_unix - 600) & (common < inject_unix)
    current = (common >= inject_unix) & (common < inject_unix + 600)
    if baseline.sum() < 30 or current.sum() < 10:
        return None
    # Pre-declared positive-skew transform, decided from baseline only.
    if np.all(x[baseline] >= 0) and np.quantile(x[baseline], .9) > 4 * max(np.median(x[baseline]), 1e-9):
        x = np.log1p(x)
    if np.all(y[baseline] >= 0) and np.quantile(y[baseline], .9) > 4 * max(np.median(y[baseline]), 1e-9):
        y = np.log1p(y)
    intercept, slope = robust_linear_fit(x[baseline], y[baseline])
    baseline_residual = y[baseline] - (intercept + slope * x[baseline])
    current_residual = y[current] - (intercept + slope * x[current])
    center = float(np.median(baseline_residual))
    scale = max(1.4826 * float(np.median(np.abs(baseline_residual - center))),
                max(1.0, abs(center)) * 1e-6)
    normalized = np.abs((current_residual - center) / scale)
    return {
        "source_name": response.source_name,
        "workload_residual_location": float(abs(np.median(current_residual) - center) / scale),
        "workload_residual_p90": float(np.quantile(normalized, .9)),
        "workload_residual_persistence": float(np.mean(normalized >= 3.5)),
        "workload_residual_peak": float(np.max(normalized)),
    }


def _empty() -> dict[str, float]:
    return {
        "workload_residual_location": 0.0,
        "workload_residual_p90": 0.0,
        "workload_residual_persistence": 0.0,
        "workload_residual_peak": 0.0,
    }

