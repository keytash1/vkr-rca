"""Strict metric adapter and soft trace/metric feature construction for M9B."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .dataset import feature_rows
from .m9b_schema import (
    FAMILY_FIELDS,
    FEATURE_COLUMNS_M9B,
    METRIC_FAMILIES,
    METRIC_SUFFIXES,
    PERCENTILE_BASE_COLUMNS,
    TRACE_FIELDS,
    validate_schema,
)

ROLLING_SECONDS = (30, 60, 120)
RESIDUAL_THRESHOLD = 3.5
_COLUMN = re.compile(r"^(.+)_([^_]+)$")
_INFRA_EXACT = {"redis", "rabbitmq", "queue", "session", "istio-proxy"}


def parse_metric_column(name: str) -> tuple[str, str] | None:
    match = _COLUMN.fullmatch(str(name))
    if not match:
        return None
    entity, suffix = match.groups()
    family = METRIC_SUFFIXES.get(suffix)
    if not entity or family is None:
        return None
    return entity, family


def normalize_entity(value: str) -> str:
    return re.sub(r"-+", "-", value.strip().lower().replace("_", "-")).strip("-")


def service_key(value: str) -> str:
    normalized = normalize_entity(value)
    if normalized.endswith("-service"):
        normalized = normalized[:-8]
    elif normalized.endswith("service"):
        normalized = normalized[:-7]
    return normalized.replace("-", "")


def is_infrastructure_entity(value: str) -> bool:
    normalized = normalize_entity(value)
    return normalized in _INFRA_EXACT or normalized.endswith(("-mongo", "-mysql", "-db"))


def match_entity(entity: str, observed_services: Iterable[str]) -> str | None:
    if is_infrastructure_entity(entity):
        return None
    observed = sorted(set(observed_services))
    if not observed:
        return normalize_entity(entity)
    wanted = service_key(entity)
    matches = [service for service in observed if service_key(service) == wanted]
    return matches[0] if len(matches) == 1 else None


def audit_metric_frame(frame: pd.DataFrame) -> dict:
    if "time" not in frame:
        raise ValueError("metric parquet has no time column")
    times = pd.to_numeric(frame["time"], errors="coerce")
    finite_times = times[np.isfinite(times)]
    ordered = finite_times.sort_values()
    deltas = ordered.diff().dropna()
    positive = deltas[deltas > 0]
    parsed = [parse_metric_column(name) for name in frame.columns if name != "time"]
    return {
        "rows": len(frame),
        "metric_columns": len(frame.columns) - 1,
        "parsed_columns": sum(value is not None for value in parsed),
        "unknown_columns": sorted(name for name in frame.columns if name != "time" and parse_metric_column(name) is None),
        "duplicate_timestamps": int(finite_times.duplicated().sum()),
        "missing_timestamps": int(times.isna().sum()),
        "cadence_seconds_median": float(positive.median()) if len(positive) else None,
        "cadence_seconds_min": float(positive.min()) if len(positive) else None,
        "cadence_seconds_max": float(positive.max()) if len(positive) else None,
        "nan_values": int(frame.drop(columns=["time"]).isna().sum().sum()),
        "inf_values": int(np.isinf(frame.drop(columns=["time"]).select_dtypes(include=[np.number])).sum().sum()),
    }


def extract_case_features(metric_path: str | Path, inject_unix: int, trace_snapshot: dict | None = None) -> dict:
    validate_schema()
    frame = pd.read_parquet(metric_path)
    audit = audit_metric_frame(frame)
    frame = frame.copy()
    frame["time"] = pd.to_numeric(frame["time"], errors="coerce")
    frame = frame[np.isfinite(frame["time"])].sort_values("time")
    if frame["time"].duplicated().any():
        frame = frame.groupby("time", as_index=False).median(numeric_only=True)
    frame = frame[(frame["time"] >= inject_unix - 600) & (frame["time"] < inject_unix + 600)]

    trace_vectors: dict[str, dict[str, float]] = {}
    observed_trace_services: list[str] = []
    if trace_snapshot is not None:
        observed_trace_services = sorted(set(trace_snapshot.get("ready_universe") or []))
        trace_vectors = dict(feature_rows(trace_snapshot)) if observed_trace_services else {}

    channels: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    entity_mapping_by_entity = {}
    unknown = []
    for column in frame.columns:
        if column == "time":
            continue
        parsed = parse_metric_column(column)
        if parsed is None:
            unknown.append(column)
            continue
        raw_entity, family = parsed
        normalized = normalize_entity(raw_entity)
        service = match_entity(raw_entity, observed_trace_services)
        entity_mapping_by_entity.setdefault(raw_entity, {
            "raw_entity": raw_entity,
            "normalized_entity": normalized,
            "matched_service": service,
            "infrastructure": is_infrastructure_entity(raw_entity),
        })
        if service is None:
            continue
        detail = channel_features(frame["time"], frame[column], inject_unix)
        if detail["available"]:
            detail["metric_name"] = column
            channels[service][family].append(detail)

    candidates = sorted(set(channels) | set(trace_vectors))
    vectors = {}
    explanations = {}
    for service in candidates:
        vector = {name: 0.0 for name in FEATURE_COLUMNS_M9B}
        family_scores = []
        family_explanations = {}
        for family in METRIC_FAMILIES:
            values = channels[service].get(family, [])
            aggregate, explanation = aggregate_family(values)
            for field in FAMILY_FIELDS:
                vector[f"metric_{family}_{field}"] = float(aggregate[field])
            if aggregate["has"]:
                family_scores.append(float(aggregate["max_shift"]))
            family_explanations[family] = explanation
        vector["metric_available_family_count"] = float(len(family_scores))
        vector["metric_available_family_ratio"] = len(family_scores) / len(METRIC_FAMILIES)
        family_scores.sort(reverse=True)
        vector["metric_max_shift_score"] = family_scores[0] if family_scores else 0.0
        vector["metric_top2_score"] = float(np.mean(family_scores[:2])) if family_scores else 0.0
        if service in trace_vectors:
            vector["has_trace"] = 1.0
            for name in TRACE_FIELDS:
                vector[f"trace_{name}"] = float(trace_vectors[service][name])
        vectors[service] = vector
        explanations[service] = family_explanations

    add_incident_percentiles(vectors)
    for service, vector in vectors.items():
        if set(vector) != set(FEATURE_COLUMNS_M9B):
            raise ValueError(f"incomplete M9B vector for {service}")
        if not all(math.isfinite(float(value)) for value in vector.values()):
            raise ValueError(f"non-finite M9B vector for {service}")
    entity_mapping = [entity_mapping_by_entity[name] for name in sorted(entity_mapping_by_entity)]
    unmatched = [value for value in entity_mapping if value["matched_service"] is None]
    return {
        "schema_version": "m9b-v1",
        "services": [{"service": service, "vector": vectors[service], "metric_explanation": explanations[service]}
                     for service in candidates],
        "candidate_services": candidates,
        "entity_mapping": entity_mapping,
        "mapping_coverage": {
            "entities": len(entity_mapping),
            "matched": len(entity_mapping) - len(unmatched),
            "unmatched": len(unmatched),
            "unmatched_infrastructure": sum(value["infrastructure"] for value in unmatched),
        },
        "audit": audit,
        "unknown_metric_columns": sorted(unknown),
    }


def channel_features(times: pd.Series, values: pd.Series, inject_unix: int) -> dict:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = np.isfinite(numeric)
    baseline_mask = finite & (times >= inject_unix - 600) & (times < inject_unix)
    current_mask = finite & (times >= inject_unix) & (times < inject_unix + 600)
    baseline = numeric[baseline_mask].to_numpy(dtype=float)
    current = numeric[current_mask].to_numpy(dtype=float)
    current_times = times[current_mask].to_numpy(dtype=float)
    if baseline.size < 30 or current.size < 10:
        return {"available": False, "baseline_samples": len(baseline), "current_samples": len(current)}
    baseline_median = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - baseline_median)))
    scale = max(1.4826 * mad, max(1.0, abs(baseline_median)) * 1e-6)
    baseline_p90 = float(np.quantile(baseline, .9))
    current_median = float(np.median(current))
    current_p90 = float(np.quantile(current, .9))
    baseline_iqr = float(np.quantile(baseline, .75) - np.quantile(baseline, .25))
    current_iqr = float(np.quantile(current, .75) - np.quantile(current, .25))
    signed = (current_median - baseline_median) / scale
    p90_shift = (current_p90 - baseline_p90) / scale
    iqr_shift = (current_iqr - baseline_iqr) / scale
    residuals = np.abs((current - baseline_median) / scale)
    exceeds = residuals >= RESIDUAL_THRESHOLD
    first = int(np.argmax(exceeds)) if exceeds.any() else None
    peak = int(np.argmax(residuals)) if residuals.size else None
    rolling = {seconds: _rolling_features(current_times, current, baseline_median, scale, seconds)
               for seconds in ROLLING_SECONDS}
    return {
        "available": True,
        "baseline_samples": len(baseline),
        "current_samples": len(current),
        "baseline_p50": baseline_median,
        "baseline_p90": baseline_p90,
        "current_p50": current_median,
        "current_p90": current_p90,
        "baseline_iqr": baseline_iqr,
        "current_iqr": current_iqr,
        "scale": scale,
        "signed_location_z": signed,
        "abs_location_z": abs(signed),
        "p90_shift_z": p90_shift,
        "iqr_shift_z": iqr_shift,
        "persistence_fraction": float(np.mean(exceeds)),
        "max_exceedance_run_fraction": _max_run(exceeds) / len(exceeds),
        "first_exceedance_fraction": first / max(1, len(exceeds) - 1) if first is not None else 0.0,
        "peak_fraction": peak / max(1, len(residuals) - 1) if peak is not None else 0.0,
        **{f"rolling_{seconds}_{field}": rolling[seconds][field]
           for seconds in ROLLING_SECONDS for field in ("score", "median", "fraction")},
    }


def aggregate_family(channels: list[dict]) -> tuple[dict, dict]:
    empty = {field: 0.0 for field in FAMILY_FIELDS}
    if not channels:
        return empty, {"available": False, "winning_metric": None, "channels": []}
    scored = []
    for value in channels:
        score = max(
            value["abs_location_z"], abs(value["p90_shift_z"]), abs(value["iqr_shift_z"]),
            *(value[f"rolling_{seconds}_score"] for seconds in ROLLING_SECONDS),
        )
        scored.append((float(score), value["metric_name"], value))
    scored.sort(key=lambda item: (-item[0], item[1]))
    winner = scored[0][2]
    top_scores = [value[0] for value in scored[:2]]
    aggregate = {
        "has": 1.0,
        "available_count": float(len(scored)),
        "baseline_samples": float(winner["baseline_samples"]),
        "current_samples": float(winner["current_samples"]),
        "max_shift": scored[0][0],
        "top2_mean_shift": float(np.mean(top_scores)),
        "max_persistence": max(value[2]["persistence_fraction"] for value in scored),
        "signed_location_z": winner["signed_location_z"],
        "abs_location_z": winner["abs_location_z"],
        "p90_shift_z": winner["p90_shift_z"],
        "iqr_shift_z": winner["iqr_shift_z"],
        "max_run_fraction": winner["max_exceedance_run_fraction"],
        "first_exceedance_fraction": winner["first_exceedance_fraction"],
        "peak_fraction": winner["peak_fraction"],
        **{f"rolling_{seconds}_{field}": winner[f"rolling_{seconds}_{field}"]
           for seconds in ROLLING_SECONDS for field in ("score", "median", "fraction")},
    }
    explanation = {
        "available": True,
        "winning_metric": winner["metric_name"],
        "winning_score": scored[0][0],
        "channel_count": len(scored),
        "winning_detail": {key: value for key, value in winner.items() if key != "available"},
    }
    return aggregate, explanation


def add_incident_percentiles(vectors: dict[str, dict[str, float]]) -> None:
    services = sorted(vectors)
    for column in PERCENTILE_BASE_COLUMNS:
        values = [float(vectors[service][column]) for service in services]
        ranks = _percentile_ranks(values)
        for service, rank in zip(services, ranks, strict=True):
            vectors[service][f"{column}_percentile"] = rank


def _percentile_ranks(values: list[float]) -> list[float]:
    if len(values) <= 1:
        return [1.0] * len(values)
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = (start + end - 1) / 2
        for position in range(start, end):
            result[order[position]] = average_rank / (len(values) - 1)
        start = end
    return result


def _rolling_features(times: np.ndarray, values: np.ndarray, baseline_median: float,
                      scale: float, seconds: int) -> dict[str, float]:
    if not len(values):
        return {"score": 0.0, "median": 0.0, "fraction": 0.0}
    index = pd.to_datetime(times, unit="s", utc=True)
    series = pd.Series(values, index=index)
    medians = series.rolling(f"{seconds}s", min_periods=1).median().to_numpy(dtype=float)
    shifts = np.abs((medians - baseline_median) / scale)
    return {"score": float(np.max(shifts)), "median": float(np.median(shifts)),
            "fraction": float(np.mean(shifts >= RESIDUAL_THRESHOLD))}


def _max_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if value else 0
        best = max(best, current)
    return best
