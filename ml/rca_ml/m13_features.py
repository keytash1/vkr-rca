"""Healthy-only workload-conditioned M13 diagnostic representation."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Sequence

import numpy as np
from sklearn.linear_model import HuberRegressor

from .m13_trace import summarize_window
from .m12_adapter import CANONICAL_UNITS

TRACE_SIGNALS = (
    "span_rate", "request_rate", "error_rate", "latency_median_us", "latency_p90_us",
    "latency_p99_us", "exclusive_median_us", "downstream_wait_ratio",
)
METRIC_SIGNALS = tuple(CANONICAL_UNITS)

DIRECT_FEATURES = tuple(
    [f"metric_{family}_{suffix}" for family in METRIC_SIGNALS for suffix in ("shift", "persistence", "available")]
    + ["metric_max_shift", "metric_second_shift", "metric_coverage", "metric_heuristic_percentile"]
)
TRACE_FEATURES = tuple(
    [f"trace_{name}_shift" for name in TRACE_SIGNALS]
    + ["trace_local_support", "trace_coverage", "exclusive_duration_support", "downstream_wait_support"]
)
PROPAGATION_FEATURES = (
    "upstream_affected_ratio", "downstream_affected_ratio", "affected_neighborhood_precision",
    "affected_neighborhood_recall", "affected_neighborhood_f1", "distance_weighted_affected_callers",
    "distance_weighted_affected_callees", "local_vs_neighbor_anomaly_contrast", "caller_error_propagation",
    "callee_latency_propagation", "expected_vs_observed_affected_region",
)
DISAPPEARANCE_FEATURES = (
    "expected_service_activity", "observed_service_activity", "activity_ratio", "span_count_drop",
    "request_count_drop", "last_seen_delta", "expected_edge_presence", "observed_edge_presence",
    "missing_expected_edge_ratio", "caller_requests_without_callee_response",
    "caller_errors_without_callee_spans", "expected_trace_presence", "observed_trace_presence",
    "telemetry_disappearance_score", "trace_collected_mask", "expected_but_disappeared_mask",
)
COVERAGE_FEATURES = (
    "topology_coverage", "candidate_count_log", "missing_metric_modality", "missing_trace_modality",
)
RANKING_FEATURES = ("base_rank_percentile", "base_relative_score", "base_margin")
FEATURES = DIRECT_FEATURES + TRACE_FEATURES + PROPAGATION_FEATURES + DISAPPEARANCE_FEATURES + COVERAGE_FEATURES

FEATURE_GROUPS = {
    "metrics": DIRECT_FEATURES,
    "traces": TRACE_FEATURES,
    "propagation": PROPAGATION_FEATURES,
    "disappearance": DISAPPEARANCE_FEATURES,
    "coverage": COVERAGE_FEATURES,
    "ranking_context": RANKING_FEATURES,
}


def fit_healthy_baseline(healthy: dict, services: Sequence[str]) -> dict:
    """Fit all normal-state expectations from healthy records only."""
    metric_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for item in healthy["metrics"]:
        segment = _segment_for(float(item["timestamp"]), healthy["segments"])
        if segment is None:
            continue
        metric_values[(str(item["service"]), str(item["family"]))].append(
            (float(segment["requests_per_second"]), float(item["value"]))
        )

    trace_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    edge_sets: list[set[tuple[str, str]]] = []
    windows = 0
    for segment in healthy["segments"]:
        left = int(float(segment["start_unix"]) * 1_000_000)
        end = int(float(segment["end_unix"]) * 1_000_000)
        while left < end:
            right = min(end, left + 10_000_000)
            summary, edges = summarize_window(healthy["traces"], services, left, right)
            rps = float(segment["requests_per_second"])
            for service, values in summary.items():
                for name in TRACE_SIGNALS:
                    trace_values[(service, name)].append((rps, float(values[name])))
            edge_sets.append(set(edges))
            windows += 1
            left = right

    return {
        "version": "m13-healthy-baseline-v1",
        "fit_role": "M13_HEALTHY_ENGINEERING",
        "metric": {service: {family: _fit(values) for (candidate, family), values in metric_values.items() if candidate == service} for service in sorted(services)},
        "trace": {service: {name: _fit(values) for (candidate, name), values in trace_values.items() if candidate == service} for service in sorted(services)},
        "expected_edges": [
            {"source": edge[0], "target": edge[1], "presence": sum(values) / max(1, len(values))}
            for edge in sorted(set().union(*edge_sets) if edge_sets else set())
            for values in [[int(edge in window) for window in edge_sets]]
            if sum(values) / max(1, len(values)) >= .5
        ],
        "windows": windows,
        "healthy_trace_count": len(healthy["traces"]),
        "healthy_metric_count": len(healthy["metrics"]),
    }


def build_candidate_rows(incident: dict, baseline: dict, services: Sequence[str]) -> list[dict]:
    """Build deterministic service rows; truth is intentionally not accepted."""
    forbidden = {"root", "root_service", "fault", "fault_family", "label", "system", "dataset"}
    leaked = forbidden & set(incident)
    if leaked:
        raise ValueError(f"truth/identity at M13 feature boundary: {sorted(leaked)}")
    services = tuple(sorted(set(map(str, services))))
    rps = float(incident["requests_per_second"])
    start_us = int(float(incident["start_unix"]) * 1_000_000)
    end_us = int(float(incident["end_unix"]) * 1_000_000)
    duration = max(float(incident["end_unix"]) - float(incident["start_unix"]), 1e-6)
    trace_summary, observed_edge_counts = summarize_window(incident["traces"], services, start_us, end_us)

    metric_grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for item in incident["metrics"]:
        metric_grouped[(str(item["service"]), str(item["family"]))].append(float(item["value"]))

    expected_edges = {(item["source"], item["target"]): float(item["presence"]) for item in baseline["expected_edges"]}
    topology_edges = set(expected_edges) | set(observed_edge_counts)
    parents, children = _graphs(services, topology_edges)
    local_scores, trace_shifts, metric_shifts = {}, {}, {}
    raw = {}
    for service in services:
        metric_family = {}
        for family in METRIC_SIGNALS:
            values = metric_grouped.get((service, family), [])
            normal = baseline["metric"].get(service, {}).get(family)
            if not values or not normal:
                metric_family[family] = {"shift": 0.0, "persistence": 0.0, "available": 0.0}
                continue
            residuals = [(value - _predict(normal, rps)) / normal["residual_iqr"] for value in values]
            absolute = np.abs(np.asarray(residuals, dtype=float))
            metric_family[family] = {
                "shift": float(np.quantile(absolute, .9)),
                "persistence": float(np.mean(absolute >= 3.0)),
                "available": 1.0,
            }
        current_trace = trace_summary[service]
        service_trace_shifts = {}
        for name in TRACE_SIGNALS:
            normal = baseline["trace"].get(service, {}).get(name)
            if not normal:
                service_trace_shifts[name] = 0.0
                continue
            value = float(current_trace[name])
            predicted = _predict(normal, rps)
            residual = (value - predicted) / normal["residual_iqr"]
            service_trace_shifts[name] = max(0.0, residual) if name in {"error_rate", "latency_median_us", "latency_p90_us", "latency_p99_us", "exclusive_median_us", "downstream_wait_ratio"} else abs(residual)
        max_metric = max((value["shift"] for value in metric_family.values()), default=0.0)
        max_trace = max(service_trace_shifts.values(), default=0.0)
        expected_spans = max(0.0, _predict(baseline["trace"].get(service, {}).get("span_rate", _empty_fit()), rps) * duration)
        expected_requests = max(0.0, _predict(baseline["trace"].get(service, {}).get("request_rate", _empty_fit()), rps) * duration)
        observed_spans = float(current_trace["span_count"])
        observed_requests = float(current_trace["request_count"])
        ratio = observed_spans / max(expected_spans, 1.0)
        expected_trace = float(expected_spans >= 1.0)
        disappeared = float(expected_trace > 0 and ratio < .2)
        outgoing_expected = {edge for edge in expected_edges if edge[0] == service}
        outgoing_observed = {edge for edge in observed_edge_counts if edge[0] == service}
        incoming_expected = {edge for edge in expected_edges if edge[1] == service}
        missing_edge_ratio = len(outgoing_expected - outgoing_observed) / max(1, len(outgoing_expected))
        incoming_seen = len(incoming_expected & set(observed_edge_counts))
        expected_presence = float(bool(outgoing_expected or incoming_expected))
        observed_presence = float(bool(outgoing_observed or incoming_seen))
        disappearance = max(0.0, min(1.0, .45 * max(0.0, 1.0-ratio) + .35 * missing_edge_ratio + .20 * disappeared)) if expected_trace else 0.0
        raw[service] = {
            "metric": metric_family,
            "trace": current_trace,
            "trace_shifts": service_trace_shifts,
            "max_metric": max_metric,
            "max_trace": max_trace,
            "expected_spans": expected_spans,
            "expected_requests": expected_requests,
            "observed_spans": observed_spans,
            "observed_requests": observed_requests,
            "activity_ratio": ratio,
            "expected_trace": expected_trace,
            "disappeared": disappeared,
            "expected_edge_presence": expected_presence,
            "observed_edge_presence": observed_presence,
            "missing_edge_ratio": missing_edge_ratio,
            "disappearance": disappearance,
        }
        metric_shifts[service] = max_metric
        trace_shifts[service] = max_trace
        local_scores[service] = max(max_metric, max_trace, disappearance * 6.0)

    percentiles = _percentiles(metric_shifts)
    affected = {service for service, score in local_scores.items() if score >= 3.0}
    rows = []
    for service in services:
        item = raw[service]
        vector = {}
        shifts = sorted((value["shift"] for value in item["metric"].values()), reverse=True)
        for family in METRIC_SIGNALS:
            for suffix in ("shift", "persistence", "available"):
                vector[f"metric_{family}_{suffix}"] = float(item["metric"][family][suffix])
        vector.update({
            "metric_max_shift": shifts[0] if shifts else 0.0,
            "metric_second_shift": shifts[1] if len(shifts) > 1 else 0.0,
            "metric_coverage": sum(value["available"] for value in item["metric"].values()) / len(METRIC_SIGNALS),
            "metric_heuristic_percentile": percentiles[service],
        })
        for name in TRACE_SIGNALS:
            vector[f"trace_{name}_shift"] = float(item["trace_shifts"][name])
        vector.update({
            "trace_local_support": min(1.0, item["max_trace"] / 6.0),
            "trace_coverage": float(item["trace"]["trace_coverage"]),
            "exclusive_duration_support": min(1.0, item["trace_shifts"]["exclusive_median_us"] / 6.0),
            "downstream_wait_support": min(1.0, item["trace_shifts"]["downstream_wait_ratio"] / 6.0),
        })
        upstream, downstream = parents[service], children[service]
        neighborhood = upstream | downstream
        affected_neighbors = neighborhood & affected
        precision = len(affected_neighbors) / max(1, len(affected))
        recall = len(affected_neighbors) / max(1, len(neighborhood))
        vector.update({
            "upstream_affected_ratio": len(upstream & affected) / max(1, len(upstream)),
            "downstream_affected_ratio": len(downstream & affected) / max(1, len(downstream)),
            "affected_neighborhood_precision": precision,
            "affected_neighborhood_recall": recall,
            "affected_neighborhood_f1": 2*precision*recall / max(precision+recall, 1e-9),
            "distance_weighted_affected_callers": _distance_score(service, affected, topology_edges, reverse=True),
            "distance_weighted_affected_callees": _distance_score(service, affected, topology_edges, reverse=False),
            "local_vs_neighbor_anomaly_contrast": local_scores[service] - float(np.mean([local_scores[name] for name in neighborhood])) if neighborhood else local_scores[service],
            "caller_error_propagation": float(np.mean([raw[name]["trace"]["error_rate"] for name in upstream])) if upstream else 0.0,
            "callee_latency_propagation": float(np.mean([raw[name]["trace_shifts"]["latency_p90_us"] for name in downstream])) if downstream else 0.0,
            "expected_vs_observed_affected_region": len(affected_neighbors) / max(1, len(affected | neighborhood)),
        })
        vector.update({
            "expected_service_activity": min(1.0, item["expected_spans"] / max(1.0, duration*rps)),
            "observed_service_activity": min(1.0, item["observed_spans"] / max(1.0, duration*rps)),
            "activity_ratio": min(2.0, item["activity_ratio"]),
            "span_count_drop": max(0.0, 1.0-item["observed_spans"]/max(item["expected_spans"], 1.0)),
            "request_count_drop": max(0.0, 1.0-item["observed_requests"]/max(item["expected_requests"], 1.0)),
            "last_seen_delta": min(1.0, item["trace"]["last_seen_delta_s"] / max(duration, 1.0)),
            "expected_edge_presence": item["expected_edge_presence"],
            "observed_edge_presence": item["observed_edge_presence"],
            "missing_expected_edge_ratio": item["missing_edge_ratio"],
            "caller_requests_without_callee_response": item["missing_edge_ratio"] * (len(upstream) > 0),
            "caller_errors_without_callee_spans": item["missing_edge_ratio"] * (float(np.mean([raw[name]["trace"]["error_rate"] for name in upstream])) if upstream else 0.0),
            "expected_trace_presence": item["expected_trace"],
            "observed_trace_presence": float(item["observed_spans"] > 0),
            "telemetry_disappearance_score": item["disappearance"],
            "trace_collected_mask": float(bool(incident["traces_collected"])),
            "expected_but_disappeared_mask": item["disappeared"],
            "topology_coverage": float(bool(topology_edges)),
            "candidate_count_log": math.log1p(len(services)),
            "missing_metric_modality": float(not any(value["available"] for value in item["metric"].values())),
            "missing_trace_modality": float(not incident["traces_collected"]),
        })
        if tuple(vector) != FEATURES:
            raise AssertionError("M13 feature schema ordering changed")
        if not all(math.isfinite(float(value)) for value in vector.values()):
            raise ValueError("non-finite M13 feature")
        rows.append({"service": service, "features": vector})
    return rows


def _fit(values: Sequence[tuple[float, float]]) -> dict:
    if not values:
        return _empty_fit()
    x = np.asarray([[item[0]] for item in values], dtype=float)
    y = np.asarray([item[1] for item in values], dtype=float)
    if len(set(float(value) for value in x[:, 0])) > 1 and len(values) >= 4:
        model = HuberRegressor(epsilon=1.35, alpha=0.0).fit(x, y)
        slope, intercept = float(model.coef_[0]), float(model.intercept_)
    else:
        slope, intercept = 0.0, float(np.median(y))
    residual = y - (intercept + slope*x[:, 0])
    q25, median, q75 = np.quantile(residual, [.25, .5, .75])
    scale = max(float(q75-q25), max(abs(float(median))*.01, abs(float(np.median(y)))*.01, 1e-9))
    return {"intercept": intercept, "slope": slope, "residual_median": float(median), "residual_iqr": scale, "samples": len(values)}


def _empty_fit() -> dict:
    return {"intercept": 0.0, "slope": 0.0, "residual_median": 0.0, "residual_iqr": 1.0, "samples": 0}


def _predict(model: dict, workload: float) -> float:
    return float(model["intercept"]) + float(model["slope"])*workload + float(model.get("residual_median", 0.0))


def _segment_for(timestamp: float, segments: Sequence[dict]) -> dict | None:
    return next((item for item in segments if float(item["start_unix"]) <= timestamp <= float(item["end_unix"])), None)


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values, key=lambda name: (values[name], name))
    return {name: ordered.index(name)/max(1, len(ordered)-1) for name in values}


def _graphs(services: Sequence[str], edges: set[tuple[str, str]]):
    direct_out = {service: set() for service in services}
    direct_in = {service: set() for service in services}
    for source, target in edges:
        if source in direct_out and target in direct_out:
            direct_out[source].add(target)
            direct_in[target].add(source)

    def closure(start: str, graph: dict[str, set[str]]) -> set[str]:
        seen, pending = set(), list(graph[start])
        while pending:
            item = pending.pop()
            if item not in seen:
                seen.add(item)
                pending.extend(graph[item])
        return seen
    return ({service: closure(service, direct_in) for service in services}, {service: closure(service, direct_out) for service in services})


def _distance_score(service: str, affected: set[str], edges: set[tuple[str, str]], *, reverse: bool) -> float:
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        graph[target if reverse else source].add(source if reverse else target)
    score, seen = 0.0, {service}
    queue = deque([(service, 0)])
    while queue:
        node, distance = queue.popleft()
        for neighbor in graph[node]:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            next_distance = distance + 1
            if neighbor in affected:
                score += 1.0 / next_distance
            queue.append((neighbor, next_distance))
    return score / max(1, len(affected))
