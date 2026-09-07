"""Generic, truth-free adapters from M12 telemetry to frozen RCA features."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_FAMILIES
from .m10d_reranker import FORBIDDEN_INFERENCE_KEYS


class MetricSource(Protocol):
    def metrics(self, incident_id: str) -> Sequence[dict]: ...


class TraceSource(Protocol):
    def traces(self, incident_id: str) -> Sequence[dict]: ...


class TopologySource(Protocol):
    def edges(self, incident_id: str) -> Sequence[dict]: ...


class IncidentSource(Protocol):
    def incident_ids(self) -> Sequence[str]: ...
    def candidate_services(self, incident_id: str) -> Sequence[str]: ...


@dataclass(frozen=True)
class CanonicalMetricSource:
    records: dict[str, list[dict]]

    def metrics(self, incident_id: str) -> Sequence[dict]:
        value = copy.deepcopy(self.records.get(incident_id, []))
        assert_truth_free(value)
        return value


@dataclass(frozen=True)
class CanonicalTraceSource:
    records: dict[str, list[dict]]

    def traces(self, incident_id: str) -> Sequence[dict]:
        value = copy.deepcopy(self.records.get(incident_id, []))
        assert_truth_free(value)
        return value


@dataclass(frozen=True)
class DeploymentTopologySource:
    records: dict[str, list[dict]]

    def edges(self, incident_id: str) -> Sequence[dict]:
        return copy.deepcopy(self.records.get(incident_id, []))


@dataclass(frozen=True)
class WindowIncidentSource:
    services: dict[str, list[str]]

    def incident_ids(self) -> Sequence[str]:
        return sorted(self.services)

    def candidate_services(self, incident_id: str) -> Sequence[str]:
        return sorted(self.services[incident_id])


CANONICAL_UNITS = {
    "cpu": "cores",
    "memory": "bytes",
    "network": "bytes_per_second",
    "traffic_rate": "bytes_per_second",
}


def assert_truth_free(records: Sequence[dict]) -> None:
    forbidden = FORBIDDEN_INFERENCE_KEYS | {"fault_type", "incident_semantic_label"}
    for record in records:
        leaked = forbidden & set(record)
        if leaked:
            raise ValueError(f"truth/identity at M12 inference boundary: {sorted(leaked)}")


def robust_baseline(records: Sequence[dict]) -> dict:
    """Fit normal-state medians/IQRs from healthy engineering data only."""
    assert_truth_free(records)
    grouped: dict[tuple[str, str], list[float]] = {}
    for item in records:
        family = str(item["family"])
        if item.get("unit") != CANONICAL_UNITS[family]:
            raise ValueError(f"bad canonical unit for {family}")
        grouped.setdefault((str(item["service"]), family), []).append(float(item["value"]))
    result = {}
    for (service, family), values in sorted(grouped.items()):
        data = np.asarray(values, dtype=float)
        if not np.all(np.isfinite(data)):
            raise ValueError("non-finite metric sample")
        q25, median, q75 = np.quantile(data, [.25, .5, .75])
        result.setdefault(service, {})[family] = {
            "median": float(median),
            "iqr": max(float(q75 - q25), max(abs(float(median)) * .01, 1e-9)),
            "samples": len(values),
        }
    return result


def canonical_features(
    records: Sequence[dict], baseline: dict, services: Sequence[str], edges: Sequence[dict]
) -> list[dict]:
    """Create service-invariant frozen feature vectors without truth metadata."""
    assert_truth_free(records)
    services = tuple(sorted(dict.fromkeys(map(str, services))))
    grouped: dict[tuple[str, str], list[float]] = {}
    for item in records:
        family = str(item["family"])
        if family not in CANONICAL_UNITS or item.get("unit") != CANONICAL_UNITS[family]:
            raise ValueError(f"unsupported metric/unit: {family}/{item.get('unit')}")
        grouped.setdefault((str(item["service"]), family), []).append(float(item["value"]))

    edge_pairs = {(str(item["source"]), str(item["target"])) for item in edges}
    ancestors, descendants = _reachability(services, edge_pairs)
    output = []
    shifts: dict[tuple[str, str], float] = {}
    persistence: dict[tuple[str, str], float] = {}
    for service in services:
        for family in CANONICAL_UNITS:
            values = grouped.get((service, family), [])
            normal = baseline.get(service, {}).get(family)
            if not values or not normal:
                continue
            z = np.abs((np.asarray(values) - normal["median"]) / normal["iqr"])
            shifts[(service, family)] = float(np.quantile(z, .90))
            persistence[(service, family)] = float(np.mean(z >= 3.0))

    percentiles = {
        family: _percentiles({s: shifts.get((s, family), 0.0) for s in services})
        for family in CANONICAL_UNITS
    }
    family_ratio = len(CANONICAL_UNITS) / len(METRIC_FAMILIES)
    n = max(1, len(services) - 1)
    for service in services:
        vector = {name: 0.0 for name in FEATURE_COLUMNS_M10C}
        for family in CANONICAL_UNITS:
            has = (service, family) in grouped and family in baseline.get(service, {})
            vector[f"metric_{family}_has"] = float(has)
            vector[f"metric_{family}_max_shift"] = shifts.get((service, family), 0.0)
            if f"metric_{family}_persistence" in vector:
                vector[f"metric_{family}_persistence"] = persistence.get((service, family), 0.0)
            vector[f"metric_{family}_max_shift_percentile"] = percentiles[family][service]
        available_shifts = sorted((shifts.get((service, family), 0.0) for family in CANONICAL_UNITS), reverse=True)
        vector["metric_available_family_count"] = float(sum(vector[f"metric_{family}_has"] for family in CANONICAL_UNITS))
        vector["metric_available_family_ratio"] = vector["metric_available_family_count"] / len(METRIC_FAMILIES)
        vector["metric_max_shift_score"] = available_shifts[0]
        vector["metric_top2_score"] = float(np.mean(available_shifts[:2]))
        vector["workload_residual_persistence"] = persistence.get((service, "traffic_rate"), 0.0)
        incoming = sum(target == service for _, target in edge_pairs)
        outgoing = sum(source == service for source, _ in edge_pairs)
        vector.update({
            "topology_in_degree": float(incoming),
            "topology_out_degree": float(outgoing),
            "topology_normalized_in_degree": incoming / n,
            "topology_normalized_out_degree": outgoing / n,
            "topology_ancestor_ratio": len(ancestors[service]) / n,
            "topology_descendant_ratio": len(descendants[service]) / n,
            "topology_active_trace_coverage": 0.0,
            "coverage_has_metrics": float(any((service, f) in grouped for f in CANONICAL_UNITS)),
            "coverage_has_traces": 0.0,
            "coverage_has_topology": 1.0,
            "coverage_metric_family_ratio": family_ratio,
            "coverage_trace_fraction": 0.0,
            "coverage_candidate_metric_ratio": sum(any((s, f) in grouped for f in CANONICAL_UNITS) for s in services) / len(services),
            "coverage_candidate_trace_ratio": 0.0,
        })
        if not all(math.isfinite(float(v)) for v in vector.values()):
            raise ValueError("non-finite feature")
        output.append({
            "service": service,
            "vector": vector,
            "metric_max_shift": max((shifts.get((service, f), 0.0) for f in CANONICAL_UNITS), default=0.0),
            "metric_family_shifts": {f: shifts.get((service, f), 0.0) for f in CANONICAL_UNITS},
        })
    return output


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    names = sorted(values)
    ordered = sorted(names, key=lambda name: (values[name], name))
    result = {}
    for name in names:
        tied = [i for i, other in enumerate(ordered) if values[other] == values[name]]
        result[name] = float(np.mean(tied) / max(1, len(names) - 1))
    return result


def _reachability(services: Sequence[str], edges: set[tuple[str, str]]):
    outgoing = {service: set() for service in services}
    incoming = {service: set() for service in services}
    for source, target in edges:
        if source in outgoing and target in outgoing:
            outgoing[source].add(target)
            incoming[target].add(source)

    def visit(start: str, graph: dict[str, set[str]]) -> set[str]:
        seen, pending = set(), list(graph[start])
        while pending:
            value = pending.pop()
            if value not in seen:
                seen.add(value)
                pending.extend(graph[value])
        return seen

    return ({s: visit(s, incoming) for s in services}, {s: visit(s, outgoing) for s in services})
