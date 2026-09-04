"""Versioned trace-only temporal anomaly detector for the M9A study."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np

DETECTOR_VERSION = "detector-v2"
FEATURE_SCHEMA_VERSION = "m9a-temporal-v1"
WINDOWS = (5, 10, 20)


@dataclass(frozen=True)
class Config:
    variant: str = "combined_temporal_v2"
    windows: tuple[int, ...] = WINDOWS
    tail_quantile: float = 0.90
    cusum_k: float = 0.5
    location_threshold: float = 2.5
    tail_threshold: float = 4.0
    cusum_threshold: float = 10.0
    error_threshold: float = 3.0
    epsilon: float = 0.1

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def robust_residuals(baseline_latency_ms: Sequence[float], current_latency_ms: Sequence[float], epsilon: float = 0.1) -> tuple[np.ndarray, dict]:
    baseline = np.log1p(np.asarray(baseline_latency_ms, dtype=float))
    current = np.log1p(np.asarray(current_latency_ms, dtype=float))
    if baseline.size == 0:
        return np.asarray([], dtype=float), {"median_log1p": 0.0, "mad_log1p": 0.0, "scale": epsilon}
    median = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - median)))
    scale = max(1.4826 * mad, epsilon)
    return np.maximum(0.0, (current - median) / scale), {"median_log1p": median, "mad_log1p": mad, "scale": scale}


def sliding_stat(values: Sequence[float], window: int, kind: str, quantile: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(values, dtype=float)
    if window <= 0 or array.size < window:
        return np.asarray([], dtype=int), np.asarray([], dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(array, window)
    result = np.median(windows, axis=1) if kind == "median" else np.quantile(windows, quantile, axis=1)
    return np.arange(window - 1, array.size), result


def positive_cusum(values: Sequence[float], k: float) -> np.ndarray:
    result = np.zeros(len(values), dtype=float)
    for index, value in enumerate(values):
        result[index] = max(0.0, (result[index - 1] if index else 0.0) + max(0.0, float(value)) - k)
    return result


def error_z(baseline: Sequence[bool | None], current: Sequence[bool | None]) -> float | None:
    base = [value for value in baseline if value is not None]
    now = [value for value in current if value is not None]
    if not base or not now:
        return None
    return _error_z_counts(sum(base), len(base), sum(now), len(now))


def _error_z_counts(e0: int, n0: int, e1: int, n1: int) -> float | None:
    if n0 == 0 or n1 == 0:
        return None
    p0 = (e0 + 0.5) / (n0 + 1)
    p1 = e1 / n1
    pooled = (e0 + 0.5 + e1) / (n0 + 1 + n1)
    variance = pooled * (1 - pooled) * (1 / (n0 + 1) + 1 / n1)
    return max(0.0, (p1 - p0) / math.sqrt(variance)) if variance > 0 else 0.0


def detect_operation(
    baseline_latency_ms: Sequence[float],
    current_latency_ms: Sequence[float],
    baseline_failed: Sequence[bool | None],
    current_failed: Sequence[bool | None],
    config: Config,
) -> dict:
    residuals, baseline_stats = robust_residuals(baseline_latency_ms, current_latency_ms, config.epsilon)
    location_score = tail_score = error_score = 0.0
    location_scale = tail_scale = error_scale = 0
    location_series: list[tuple[int, float]] = []
    tail_series: list[tuple[int, float]] = []
    error_series: list[tuple[int, float]] = []
    baseline_errors = [value for value in baseline_failed if value is not None]
    error_available = bool(baseline_errors) and any(value is not None for value in current_failed)
    baseline_error_count = int(sum(baseline_errors))
    known_prefix = np.concatenate(([0], np.cumsum([value is not None for value in current_failed], dtype=int)))
    error_prefix = np.concatenate(([0], np.cumsum([bool(value) if value is not None else False for value in current_failed], dtype=int)))
    for window in config.windows:
        indices, locations = sliding_stat(residuals, window, "median")
        if locations.size and float(np.max(locations)) > location_score:
            location_score, location_scale = float(np.max(locations)), window
        location_series.extend(zip(indices.tolist(), locations.tolist()))
        indices, tails = sliding_stat(residuals, window, "quantile", config.tail_quantile)
        if tails.size and float(np.max(tails)) > tail_score:
            tail_score, tail_scale = float(np.max(tails)), window
        tail_series.extend(zip(indices.tolist(), tails.tolist()))
        if error_available and len(current_failed) >= window:
            for end in range(window, len(current_failed) + 1):
                begin = end - window
                known_count = int(known_prefix[end] - known_prefix[begin])
                error_count = int(error_prefix[end] - error_prefix[begin])
                value = _error_z_counts(baseline_error_count, len(baseline_errors), error_count, known_count)
                numeric = float(value or 0.0)
                error_series.append((end - 1, numeric))
                if numeric > error_score:
                    error_score, error_scale = numeric, window
    cusum = positive_cusum(residuals, config.cusum_k)
    cusum_score = float(np.max(cusum)) if cusum.size else 0.0
    channels = _channels(config.variant)
    normalized = {
        "location": location_score / config.location_threshold,
        "tail": tail_score / config.tail_threshold,
        "cusum": cusum_score / config.cusum_threshold,
        "error": error_score / config.error_threshold if error_available else -1.0,
    }
    enabled = {name: value for name, value in normalized.items() if name in channels}
    anomaly_score = max(enabled.values(), default=0.0)
    anomalous = anomaly_score >= 1.0
    event_scores: dict[int, float] = {}
    for name, series, threshold in (
        ("location", location_series, config.location_threshold),
        ("tail", tail_series, config.tail_threshold),
        ("error", error_series, config.error_threshold),
    ):
        if name in channels:
            for index, score in series:
                event_scores[index] = max(event_scores.get(index, 0.0), score / threshold)
    if "cusum" in channels:
        for index, score in enumerate(cusum):
            event_scores[index] = max(event_scores.get(index, 0.0), float(score) / config.cusum_threshold)
    onset = next((index for index in sorted(event_scores) if event_scores[index] >= 1.0), None)
    point_exceeds = residuals >= config.location_threshold
    return {
        "detector_version": DETECTOR_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "location_score": location_score,
        "tail_score": tail_score,
        "cusum_score": cusum_score,
        "error_temporal_score": error_score if error_available else None,
        "error_channel_available": error_available,
        "selected_scale": _selected_scale(enabled, location_scale, tail_scale, error_scale),
        "anomaly_score": anomaly_score,
        "anomalous": anomalous,
        "onset_index": onset,
        "onset_fraction": onset / max(1, len(residuals) - 1) if onset is not None else None,
        "persistence_fraction": float(np.mean(point_exceeds)) if residuals.size else 0.0,
        "max_exceedance_run": _max_run(point_exceeds),
        "valid_baseline_samples": len(baseline_latency_ms),
        "valid_current_samples": len(current_latency_ms),
        "baseline": baseline_stats,
        "config_sha256": config.digest(),
    }


def detect_service(operations: dict[str, dict], config: Config, min_baseline: int = 30, min_current: int = 10) -> dict:
    results = []
    for operation, values in sorted(operations.items()):
        if len(values["baseline_latency_ms"]) < min_baseline or len(values["current_latency_ms"]) < min_current:
            continue
        result = detect_operation(values["baseline_latency_ms"], values["current_latency_ms"],
                                  values["baseline_failed"], values["current_failed"], config)
        results.append({"operation": operation, **result})
    winner = max(results, key=lambda value: (value["anomaly_score"], value["operation"]), default=None)
    return {
        "anomalous": any(value["anomalous"] for value in results),
        "service_score": winner["anomaly_score"] if winner else 0.0,
        "winning_operation": winner["operation"] if winner else None,
        "operations": results,
    }


def config_grid() -> list[Config]:
    result = [Config(variant="multiscale_location", location_threshold=location)
              for location in (2.5, 3.5)]
    result += [Config(variant="multiscale_location_tail", tail_quantile=quantile,
                      location_threshold=location, tail_threshold=tail)
               for quantile in (0.90, 0.95) for location in (2.5, 3.5) for tail in (4.0, 5.0)]
    result += [Config(variant="cusum", cusum_k=k, cusum_threshold=threshold)
               for k in (0.25, 0.5, 1.0) for threshold in (8.0, 12.0, 20.0)]
    result += [Config(variant="combined_temporal_v2", tail_quantile=quantile, cusum_k=k,
                      location_threshold=location, tail_threshold=tail, cusum_threshold=cusum_threshold)
               for quantile in (0.90, 0.95) for k in (0.25, 0.5, 1.0)
               for location in (2.5, 3.5) for tail in (4.0, 5.0)
               for cusum_threshold in (8.0, 12.0, 20.0)]
    unique = {config.digest(): config for config in result}
    return [unique[key] for key in sorted(unique)]


def _channels(variant: str) -> set[str]:
    return {
        "multiscale_location": {"location", "error"},
        "multiscale_location_tail": {"location", "tail", "error"},
        "cusum": {"cusum", "error"},
        "combined_temporal_v2": {"location", "tail", "cusum", "error"},
    }[variant]


def _selected_scale(enabled: dict[str, float], location: int, tail: int, error: int) -> int:
    if not enabled:
        return 0
    winner = max(enabled, key=lambda name: (enabled[name], name))
    return {"location": location, "tail": tail, "error": error, "cusum": 0}[winner]


def _max_run(values: Sequence[bool]) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def finite_output(value: dict) -> bool:
    for item in value.values():
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, dict) and not finite_output(item):
            return False
        if isinstance(item, list) and any(isinstance(child, dict) and not finite_output(child) for child in item):
            return False
    return True
