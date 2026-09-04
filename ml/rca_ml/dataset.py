"""Truth-free M6 snapshots to validated m7-v1 candidate tables."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np

from .schema import FEATURE_COLUMNS, SOURCE_FEATURE_SCHEMA_VERSION, validate_schema


def read_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def write_jsonl(path: str | Path, records: Iterable[dict]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            output.write("\n")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enrich_labels(feature_records: Sequence[dict], labels: Sequence[dict]) -> list[dict]:
    features_by_id = {record["incident_id"]: record for record in feature_records}
    if len(features_by_id) != len(feature_records):
        raise ValueError("duplicate incident_id in features")
    result = []
    for original in labels:
        label = dict(original)
        generation_metadata = dict(label.get("generation_metadata") or {})
        generation_metadata.setdefault("top_up_cycles", 0)
        generation_metadata.setdefault("traffic_requests", 20)
        label["generation_metadata"] = generation_metadata
        record = features_by_id.get(label["incident_id"])
        if record is None:
            raise ValueError(f"missing features for {label['incident_id']}")
        snapshot = record["feature_snapshot"]
        if snapshot.get("feature_schema_version") != SOURCE_FEATURE_SCHEMA_VERSION:
            raise ValueError("unsupported M6 feature schema")
        ready = list(snapshot.get("ready_universe") or [])
        is_fault = label.get("incident_type") == "fault"
        detected = snapshot.get("state") == "ready"
        root_ready = is_fault and label.get("root_service") in ready
        label.update(
            {
                "detected": detected,
                "detection_miss": bool(is_fault and not detected),
                "root_ready": bool(root_ready),
                "ready_group_size": len(ready),
                "localization_eligible": bool(is_fault and detected and root_ready),
                "training_eligible": bool(is_fault and detected and root_ready and len(ready) >= 2),
                "trivial_group": bool(is_fault and detected and root_ready and len(ready) == 1),
            }
        )
        result.append(label)
    if set(features_by_id) != {label["incident_id"] for label in result}:
        raise ValueError("features and labels incident sets differ")
    return result


def build_candidate_rows(
    feature_records: Sequence[dict],
    labels: Sequence[dict],
    assignments: dict[str, str] | None = None,
) -> list[dict]:
    validate_schema()
    labels_by_id = {label["incident_id"]: label for label in labels}
    eligible_ids = sorted(
        record["incident_id"]
        for record in feature_records
        if labels_by_id.get(record["incident_id"], {}).get("localization_eligible")
    )
    qids = {incident_id: index for index, incident_id in enumerate(eligible_ids)}
    rows: list[dict] = []
    for record in sorted(feature_records, key=lambda value: value["incident_id"]):
        incident_id = record["incident_id"]
        label = labels_by_id.get(incident_id)
        if label is None or not label.get("localization_eligible"):
            continue
        snapshot = record["feature_snapshot"]
        numeric = feature_rows(snapshot)
        for service, values in numeric:
            row = {
                "incident_id": incident_id,
                "qid": qids[incident_id],
                "service": service,
                "label": int(service == label["root_service"]),
                "split": (assignments or {}).get(incident_id, "unassigned"),
            }
            row.update(values)
            rows.append(row)
    validate_candidate_rows(rows, labels_by_id)
    return rows


def feature_rows(snapshot: dict) -> list[tuple[str, dict[str, float]]]:
    if snapshot.get("feature_schema_version") != SOURCE_FEATURE_SCHEMA_VERSION:
        raise ValueError("unsupported M6 feature schema")
    ready = sorted(set(snapshot.get("ready_universe") or []))
    ready_set = set(ready)
    observed = set(snapshot.get("observed_anomalies") or [])
    service_vectors = {value["service"]: value for value in snapshot.get("services") or []}
    edges = [
        (edge["caller"], edge["callee"])
        for edge in snapshot.get("topology_edges") or []
        if edge.get("caller") in ready_set and edge.get("callee") in ready_set and edge.get("caller") != edge.get("callee")
    ]
    graph = _graph_features(ready, edges)
    size = len(ready)
    denominator = max(1, size)
    result: list[tuple[str, dict[str, float]]] = []
    for service in ready:
        vector = service_vectors.get(service)
        if vector is None or not vector.get("ready"):
            raise ValueError(f"ready service {service} has no ready feature vector")
        expected_count = len(set(vector.get("expected_affected_services") or []))
        values = {
            "latency_z_log1p": _log1p(vector.get("latency_z", 0)),
            "error_z_log1p": _log1p(vector.get("error_z", 0)),
            "latency_strength": vector.get("latency_strength", 0),
            "error_strength": vector.get("error_strength", 0),
            "latency_anomalous": vector.get("latency_anomalous", False),
            "error_anomalous": vector.get("error_anomalous", False),
            "m5_severity_log1p": _log1p(vector.get("m5_severity", 0)),
            "topology_precision": vector.get("topology_precision", 0),
            "topology_recall": vector.get("topology_recall", 0),
            "topology_f1": vector.get("topology_f1", 0),
            "local_evidence": vector.get("local_evidence", 0),
            "trace_coverage": vector.get("trace_coverage", 0),
            "median_exclusive_ratio": vector.get("median_exclusive_ratio", 0),
            "median_downstream_wait_ratio": vector.get("median_downstream_wait_ratio", 0),
            "log1p_median_exclusive_duration_ms": _log1p(vector.get("median_exclusive_duration_ms", 0)),
            "active_topology_trace_coverage": snapshot.get("active_topology_trace_coverage", 0),
            "is_observed_anomaly": service in observed,
            "expected_affected_count": expected_count,
            "expected_affected_ratio": expected_count / denominator,
            "ready_universe_size": size,
            "observed_anomaly_count": len(observed),
            "observed_anomaly_ratio": len(observed) / denominator,
            "primary_signal_latency": snapshot.get("primary_signal") == "latency",
            "primary_signal_error": snapshot.get("primary_signal") == "error",
            "topology_source_active": snapshot.get("topology_source") == "active_traces",
        }
        values.update(graph[service])
        converted = {name: float(values[name]) for name in FEATURE_COLUMNS}
        if not all(math.isfinite(value) for value in converted.values()):
            raise ValueError(f"non-finite feature for {service}")
        result.append((service, converted))
    return result


def validate_candidate_rows(rows: Sequence[dict], labels_by_id: dict[str, dict] | None = None) -> None:
    validate_schema()
    previous = None
    closed: set[str] = set()
    groups: dict[str, list[dict]] = defaultdict(list)
    qid_owners: dict[int, str] = {}
    for row in rows:
        incident_id = row["incident_id"]
        if previous is not None and incident_id != previous:
            closed.add(previous)
        if incident_id in closed:
            raise ValueError("candidate rows for an incident must be contiguous")
        previous = incident_id
        values = [row[column] for column in FEATURE_COLUMNS]
        if not all(isinstance(value, (bool, int, float)) and math.isfinite(float(value)) for value in values):
            raise ValueError("model matrix must be numeric and finite")
        groups[incident_id].append(row)
        qid = int(row["qid"])
        owner = qid_owners.setdefault(qid, incident_id)
        if owner != incident_id:
            raise ValueError("qid is shared by multiple incidents")
    for incident_id, group in groups.items():
        if len({int(row["qid"]) for row in group}) != 1:
            raise ValueError(f"incident {incident_id} has multiple qids")
        positives = sum(int(row["label"]) for row in group)
        if positives != 1:
            raise ValueError(f"incident {incident_id} has {positives} positives")
        if labels_by_id and labels_by_id[incident_id].get("training_eligible") and len(group) < 2:
            raise ValueError(f"training incident {incident_id} has fewer than two candidates")


def matrix_for_incidents(rows: Sequence[dict], incident_ids: Iterable[str]) -> tuple[np.ndarray, np.ndarray, list[int], list[dict]]:
    wanted = set(incident_ids)
    selected = [row for row in rows if row["incident_id"] in wanted]
    selected.sort(key=lambda row: (row["incident_id"], row["service"]))
    validate_candidate_rows(selected)
    groups: list[int] = []
    previous = None
    for row in selected:
        if row["incident_id"] != previous:
            groups.append(0)
            previous = row["incident_id"]
        groups[-1] += 1
    matrix = np.asarray([[row[column] for column in FEATURE_COLUMNS] for row in selected], dtype=np.float32)
    target = np.asarray([row["label"] for row in selected], dtype=np.float32)
    return matrix, target, groups, selected


def rankings_from_scores(rows: Sequence[dict], scores: Sequence[float]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        grouped[row["incident_id"]].append({"service": row["service"], "ml_score": float(score)})
    result = {}
    for incident_id, ranking in grouped.items():
        ranking.sort(key=lambda item: (-item["ml_score"], item["service"]))
        for index, item in enumerate(ranking, 1):
            item["rank"] = index
        result[incident_id] = ranking
    return result


def ranks_for_truth(rankings: dict[str, list[dict]], labels_by_id: dict[str, dict]) -> dict[str, int]:
    result = {}
    for incident_id, ranking in rankings.items():
        truth = labels_by_id[incident_id]["root_service"]
        result[incident_id] = next((item["rank"] for item in ranking if item["service"] == truth), 0)
    return result


def _graph_features(services: Sequence[str], edges: Sequence[tuple[str, str]]) -> dict[str, dict[str, float]]:
    forward: dict[str, set[str]] = {service: set() for service in services}
    reverse: dict[str, set[str]] = {service: set() for service in services}
    for caller, callee in sorted(set(edges)):
        forward[caller].add(callee)
        reverse[callee].add(caller)
    normalizer = max(1, len(services) - 1)
    result = {}
    for service in services:
        ancestors = _reachable(service, reverse)
        descendants = _reachable(service, forward)
        result[service] = {
            "in_degree": float(len(reverse[service])),
            "out_degree": float(len(forward[service])),
            "normalized_in_degree": len(reverse[service]) / normalizer,
            "normalized_out_degree": len(forward[service]) / normalizer,
            "ancestor_count": float(len(ancestors)),
            "descendant_count": float(len(descendants)),
            "ancestor_ratio": len(ancestors) / normalizer,
            "descendant_ratio": len(descendants) / normalizer,
        }
    return result


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    reached: set[str] = set()
    queue = deque(sorted(graph[start]))
    while queue:
        service = queue.popleft()
        if service == start or service in reached:
            continue
        reached.add(service)
        queue.extend(sorted(graph.get(service, ())))
    return reached


def _log1p(value: object) -> float:
    numeric = float(value or 0)
    return math.log1p(max(0.0, numeric)) if math.isfinite(numeric) else 0.0
