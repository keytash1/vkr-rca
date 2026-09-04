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
