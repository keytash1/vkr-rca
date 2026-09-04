"""Small deterministic synthetic M6 records used only for ML pipeline tests."""

from __future__ import annotations

import hashlib

from .dataset import enrich_labels

SERVICES = ("gateway", "orders", "payment")
EDGES = (("gateway", "orders"), ("orders", "payment"))


def fixture_dataset(incidents_per_pair: int = 5, healthy_controls: int = 3) -> tuple[list[dict], list[dict]]:
    features = []
    labels = []
    sequence = 0
    for root in SERVICES:
        for fault_type in ("latency", "error"):
            for pair_index in range(incidents_per_pair):
                incident_id = f"fixture-{sequence:04d}"
                sequence += 1
                intensity = 20 + pair_index * 30 if fault_type == "latency" else 0.2 + pair_index * 0.1
                snapshot, rankings = _snapshot(root, fault_type, float(intensity))
                features.append({"incident_id": incident_id, "feature_snapshot": snapshot, "m6_rankings": rankings})
                labels.append(
                    {
                        "incident_id": incident_id,
                        "incident_type": "fault",
                        "root_service": root,
                        "fault_type": fault_type,
                        "fault_value": intensity,
                        "generation_seed": 7,
                        "pair_index": pair_index,
                        "scenario_fingerprint": hashlib.sha256(
                            f"{root}:{fault_type}:{intensity}:{pair_index}".encode()
                        ).hexdigest(),
                    }
                )
    for index in range(healthy_controls):
        incident_id = f"fixture-{sequence:04d}"
        sequence += 1
        snapshot, rankings = _snapshot(None, "none", 0)
        features.append({"incident_id": incident_id, "feature_snapshot": snapshot, "m6_rankings": rankings})
        labels.append(
            {
                "incident_id": incident_id,
                "incident_type": "healthy",
                "root_service": None,
                "fault_type": "none",
                "fault_value": 0,
                "generation_seed": 7,
                "pair_index": index,
                "scenario_fingerprint": hashlib.sha256(f"healthy:{index}".encode()).hexdigest(),
            }
        )
    return features, enrich_labels(features, labels)


def fixture_topology_dataset(
    topology_id: str,
    services: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    incidents_per_pair: int = 3,
    healthy_controls: int = 2,
) -> tuple[list[dict], list[dict]]:
    """Small arbitrary-topology dataset for M8A pipeline tests."""
    features = []
    labels = []
    sequence = 0
    for root in services:
        for fault_type in ("latency", "error"):
            for pair_index in range(incidents_per_pair):
                incident_id = f"fixture-{topology_id.lower()}-{sequence:04d}"
                sequence += 1
                affected = _ancestors(root, services, edges)
                snapshot = _generic_snapshot(services, edges, root, fault_type, affected)
                features.append(
                    {
                        "incident_id": incident_id,
                        "feature_snapshot": snapshot,
                        "m6_rankings": {"rankings": _generic_rankings(snapshot, root)},
                        "m5_anomalies": {"baseline_state": "frozen", "operations": []},
                    }
                )
                labels.append(
                    {
                        "incident_id": incident_id,
                        "topology_id": topology_id,
                        "experiment_kind": "zero_shot",
                        "incident_type": "fault",
                        "temporal_profile": "constant",
                        "root_service": root,
                        "expected_affected_services": affected,
                        "fault_type": fault_type,
                        "fault_value": 100 if fault_type == "latency" else 0.8,
                        "scenario_fingerprint": hashlib.sha256(incident_id.encode()).hexdigest(),
                    }
                )
    for index in range(healthy_controls):
        incident_id = f"fixture-{topology_id.lower()}-healthy-{index:03d}"
        snapshot = _generic_snapshot(services, edges, None, "none", [])
        features.append(
            {
                "incident_id": incident_id,
                "feature_snapshot": snapshot,
                "m6_rankings": {"rankings": {name: [] for name in ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1")}},
                "m5_anomalies": {"baseline_state": "frozen", "operations": []},
            }
        )
        labels.append(
            {
                "incident_id": incident_id,
                "topology_id": topology_id,
                "experiment_kind": "zero_shot",
                "incident_type": "healthy",
                "temporal_profile": "healthy",
                "root_service": None,
                "expected_affected_services": [],
                "fault_type": "none",
                "fault_value": 0,
                "scenario_fingerprint": hashlib.sha256(incident_id.encode()).hexdigest(),
            }
        )
    return features, enrich_labels(features, labels)


def _ancestors(root: str, services: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> list[str]:
    reverse = {service: set() for service in services}
    for source, target in edges:
        reverse[target].add(source)
    result = {root}
    pending = [root]
    while pending:
        for parent in reverse[pending.pop()]:
            if parent not in result:
                result.add(parent)
                pending.append(parent)
    return sorted(result)


def _generic_snapshot(services, edges, root, fault_type, affected) -> dict:
    observed = set(affected)
    vectors = []
    for service in services:
        candidate_affected = _ancestors(service, services, edges)
        intersection = len(set(candidate_affected) & observed)
        precision = intersection / len(candidate_affected) if candidate_affected and observed else 0.0
        recall = intersection / len(observed) if observed else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        is_root = service == root
        is_observed = service in observed
        strength = 0.95 if is_observed else 0.0
        vectors.append(
            {
                "service": service,
                "ready": True,
                "candidate": is_observed,
                "latency_z": 12.0 if fault_type == "latency" and is_observed else 0.0,
                "error_z": 8.0 if fault_type == "error" and is_observed else 0.0,
                "latency_strength": strength if fault_type == "latency" else 0.0,
                "error_strength": strength if fault_type == "error" else 0.0,
                "latency_anomalous": fault_type == "latency" and is_observed,
                "error_anomalous": fault_type == "error" and is_observed,
                "m5_severity": 4.0 if is_observed else 0.0,
                "topology_precision": precision,
                "topology_recall": recall,
                "topology_f1": f1,
                "local_evidence": 0.95 if is_root else (0.2 if is_observed else 0.0),
                "trace_coverage": 1.0,
                "median_exclusive_ratio": 0.9 if is_root else 0.1,
                "median_downstream_wait_ratio": 0.1 if is_root else 0.9,
                "median_exclusive_duration_ms": 100.0 if is_root else 1.0,
                "expected_affected_services": candidate_affected,
            }
        )
    return {
        "feature_schema_version": "m6-v1",
        "baseline_state": "frozen",
        "state": "ready" if root else "no_anomaly",
        "primary_signal": fault_type if root else "none",
        "topology_source": "active_traces",
        "active_topology_trace_coverage": 1.0,
        "topology_edges": [{"caller": source, "callee": target} for source, target in edges],
        "ready_universe": list(services),
        "observed_anomalies": sorted(observed),
        "services": vectors,
    }


def _generic_rankings(snapshot: dict, root: str) -> dict[str, list[dict]]:
    vectors = snapshot["services"]
    scores = {
        "max_severity": lambda value: value["m5_severity"],
        "topology_consistency": lambda value: value["topology_f1"],
        "local_evidence": lambda value: value["local_evidence"],
        "hybrid_v1": lambda value: value["topology_f1"] * value["local_evidence"],
    }
    result = {}
    for name, score in scores.items():
        ranking = sorted(
            ({"service": value["service"], "score": float(score(value))} for value in vectors),
            key=lambda item: (-item["score"], item["service"]),
        )
        for rank, item in enumerate(ranking, 1):
            item["rank"] = rank
        result[name] = ranking
    return result


def _snapshot(root: str | None, fault_type: str, intensity: float) -> tuple[dict, dict]:
    ancestors = {
        "gateway": ["gateway"],
        "orders": ["gateway", "orders"],
        "payment": ["gateway", "orders", "payment"],
    }
    observed = ancestors.get(root, [])
    primary = fault_type if root else "none"
    affected_by_candidate = {
        "gateway": ["gateway"],
        "orders": ["gateway", "orders"],
        "payment": ["gateway", "orders", "payment"],
    }
    services = []
    for service in SERVICES:
        anomalous = service in observed
        is_root = service == root
        strength = min(0.99, 0.55 + intensity / (intensity + 100)) if anomalous else 0.03
        local = strength if fault_type == "error" and anomalous else strength * (0.95 if is_root else 0.03)
        predicted = affected_by_candidate[service]
        intersection = len(set(predicted) & set(observed))
        precision = intersection / len(predicted) if predicted and observed else 0
        recall = intersection / len(observed) if observed else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        z = intensity / 10 + 4 if anomalous else 0.2
        services.append(
            {
                "service": service,
                "ready": True,
                "candidate": anomalous,
                "primary_signal": primary,
                "topology_source": "active_traces",
                "active_topology_trace_coverage": 1,
                "latency_z": z if fault_type == "latency" else 0.2,
                "error_z": z if fault_type == "error" else 0,
                "latency_strength": strength if fault_type == "latency" else 0.02,
                "error_strength": strength if fault_type == "error" else 0,
                "latency_anomalous": anomalous and fault_type == "latency",
                "error_anomalous": anomalous and fault_type == "error",
                "m5_severity": z / 3.5 if anomalous else 0.05,
                "topology_precision": precision,
                "topology_recall": recall,
                "topology_f1": f1,
                "expected_affected_services": predicted,
                "trace_coverage": 1,
                "median_exclusive_ratio": 0.95 if is_root else 0.03,
                "median_exclusive_duration_ms": intensity if is_root else 0.2,
                "median_downstream_wait_ratio": 0.05 if is_root else 0.97,
                "local_evidence": local,
            }
        )
    snapshot = {
        "feature_schema_version": "m6-v1",
        "baseline_state": "frozen",
        "state": "ready" if root else "no_anomaly",
        "primary_signal": primary,
        "topology_source": "active_traces",
        "active_topology_trace_coverage": 1,
        "topology_edges": [{"caller": caller, "callee": callee} for caller, callee in EDGES],
        "ready_universe": list(SERVICES),
        "observed_anomalies": observed,
        "services": services,
    }
    ranking_names = {
        "max_severity": list(observed),
        "topology_consistency": list(reversed(observed)),
        "local_evidence": list(observed),
        "hybrid_v1": list(reversed(observed)),
    }
    rankings = {
        "rankings": {
            name: [{"rank": index, "service": service, "score": 1 / index} for index, service in enumerate(order, 1)]
            for name, order in ranking_names.items()
        }
    }
    return snapshot, rankings
