"""Truth-free compact M10C feature generation over the generic candidate union."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .dataset import read_jsonl, sha256_file
from .m10c_candidates import RCAEvalFrameSource, generate_candidates, resolve_metric_entity
from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_FAMILIES, validate_schema
from .m10c_workload import conditioned_residual_features
from .m9b_features import channel_features
from .train import save_json

SEED = 20260905
FAMILY_TO_M9B = {
    "traffic_rate": ("workload",), "error_rate": ("error",),
    "latency": ("latency_p50", "latency_p90"), "cpu": ("cpu",),
    "memory": ("memory",), "disk": ("disk_io",), "network": ("socket",),
}


def extract_features(frame: pd.DataFrame, inject_unix: int, trace_features: dict) -> dict:
    validate_schema()
    source = RCAEvalFrameSource(frame)
    trace_rows = {item["service"]: item["vector"] for item in trace_features.get("services", [])
                  if float(item["vector"].get("has_trace", 0)) > 0}
    trace_names = sorted(trace_rows)
    topology_names = [name for name, vector in trace_rows.items() if _has_topology(vector)]
    candidates = generate_candidates(source, trace_names, topology_names)

    entity_target = {entity: resolve_metric_entity(entity, trace_names) for entity in source.list_entities()}
    vectors = {candidate.name: {name: 0.0 for name in FEATURE_COLUMNS_M10C} for candidate in candidates}
    family_details: dict[str, dict[str, list[dict]]] = {
        candidate.name: {family: [] for family in METRIC_FAMILIES} for candidate in candidates
    }
    workload: dict[str, list[dict[str, float]]] = {candidate.name: [] for candidate in candidates}
    for entity, target in entity_target.items():
        if target is None:
            continue
        for family in source.list_families():
            for series in source.read_series(entity, family):
                detail = channel_features(pd.Series(series.timestamps), pd.Series(series.values), inject_unix)
                if detail["available"]:
                    family_details[target][family].append(detail)
        workload[target].append(conditioned_residual_features(source, entity, inject_unix))

    for candidate in candidates:
        vector = vectors[candidate.name]
        scores = []
        for family in METRIC_FAMILIES:
            details = family_details[candidate.name][family]
            vector[f"metric_{family}_has"] = float(bool(details))
            if details:
                shifts = [max(float(value["abs_location_z"]), abs(float(value["p90_shift_z"])),
                              *(float(value[f"rolling_{seconds}_score"]) for seconds in (30, 60, 120)))
                          for value in details]
                vector[f"metric_{family}_max_shift"] = max(shifts)
                vector[f"metric_{family}_persistence"] = max(float(value["persistence_fraction"])
                                                               for value in details)
                scores.append(max(shifts))
        scores.sort(reverse=True)
        vector["metric_available_family_count"] = float(sum(
            vector[f"metric_{family}_has"] for family in METRIC_FAMILIES))
        vector["metric_available_family_ratio"] = vector["metric_available_family_count"] / len(METRIC_FAMILIES)
        vector["metric_max_shift_score"] = scores[0] if scores else 0.0
        vector["metric_top2_score"] = float(np.mean(scores[:2])) if scores else 0.0
        if workload[candidate.name]:
            for name in ("workload_residual_location", "workload_residual_p90",
                         "workload_residual_persistence", "workload_residual_peak"):
                vector[name] = max(value[name] for value in workload[candidate.name])
        _copy_trace(vector, trace_rows.get(candidate.name, {}))
        vector["coverage_has_metrics"] = float(candidate.has_metrics)
        vector["coverage_has_traces"] = float(candidate.has_traces)
        vector["coverage_has_topology"] = float(candidate.has_topology)
        vector["coverage_metric_family_ratio"] = vector["metric_available_family_ratio"]

    _add_percentiles(vectors)
    metric_ratio = sum(value.has_metrics for value in candidates) / max(1, len(candidates))
    trace_ratio = sum(value.has_traces for value in candidates) / max(1, len(candidates))
    for candidate in candidates:
        vector = vectors[candidate.name]
        vector["coverage_trace_fraction"] = trace_ratio
        vector["coverage_candidate_metric_ratio"] = metric_ratio
        vector["coverage_candidate_trace_ratio"] = trace_ratio
        if not all(np.isfinite(float(value)) for value in vector.values()):
            raise ValueError(f"non-finite M10C vector for {candidate.name}")
    return {
        "schema_version": "m10c-v2-candidate",
        "candidate_services": [candidate.name for candidate in candidates],
        "candidates": [candidate.__dict__ for candidate in candidates],
        "services": [{"service": candidate.name, "vector": vectors[candidate.name]} for candidate in candidates],
        "source_families": list(source.list_families()),
    }


def _has_topology(vector: dict) -> bool:
    return any(float(vector.get(name, 0)) != 0 for name in (
        "trace_in_degree", "trace_out_degree", "trace_ancestor_count", "trace_descendant_count"
    ))


def _copy_trace(target: dict, source: dict) -> None:
    direct = (
        "latency_z_log1p", "error_z_log1p", "latency_strength", "error_strength",
        "m5_severity_log1p", "local_evidence", "trace_coverage", "median_exclusive_ratio",
        "median_downstream_wait_ratio", "log1p_median_exclusive_duration_ms",
        "latency_anomalous", "error_anomalous",
    )
    for name in direct:
        target[f"trace_{name}"] = float(source.get(f"trace_{name}", 0))
    topology = {
        "topology_in_degree": "trace_in_degree",
        "topology_out_degree": "trace_out_degree",
        "topology_normalized_in_degree": "trace_normalized_in_degree",
        "topology_normalized_out_degree": "trace_normalized_out_degree",
        "topology_ancestor_ratio": "trace_ancestor_ratio",
        "topology_descendant_ratio": "trace_descendant_ratio",
        "topology_active_trace_coverage": "trace_active_topology_trace_coverage",
    }
    for destination, origin in topology.items():
        target[destination] = float(source.get(origin, 0))


def _add_percentiles(vectors: dict[str, dict[str, float]]) -> None:
    names = sorted(vectors)
    bases = [f"metric_{family}_max_shift" for family in METRIC_FAMILIES] + [
        "trace_latency_z_log1p", "trace_error_z_log1p", "trace_median_exclusive_ratio",
        "trace_median_downstream_wait_ratio",
    ]
    for base in bases:
        values = np.asarray([vectors[name][base] for name in names], dtype=float)
        order = np.argsort(values, kind="stable")
        ranks = np.empty(len(values), dtype=float)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            ranks[order[start:end]] = (start + end - 1) / 2 / max(1, len(order) - 1)
            start = end
        destination = base + "_percentile"
        for name, rank in zip(names, ranks, strict=True):
            vectors[name][destination] = float(rank)


def generate(data_dir: Path, m9b_truth_free: Path, output: Path) -> dict:
    index = pd.read_parquet(data_dir / "cases.parquet", columns=["case", "inject_time"])
    inject = {str(row.case): int(row.inject_time) for row in index.itertuples(index=False)}
    old = read_jsonl(m9b_truth_free)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for position, record in enumerate(old, 1):
            case_id = record["external_case_id"]
            frame = pd.read_parquet(data_dir / case_id / "metrics.parquet")
            features = extract_features(frame, inject[case_id], record["features"])
            value = {
                "position": position, "external_case_id": case_id,
                "dataset": record["dataset"], "system": record["system"],
                "metric_sha256": record["metric_sha256"], "features": features,
            }
            stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
            if position % 50 == 0 or position == len(old):
                print(f"m10c features {position}/{len(old)} {case_id}", flush=True)
    seal = {
        "schema": "m10c-v2-candidate", "records": len(old),
        "sha256": sha256_file(output), "sealed_before_label_join": True,
        "source_truth_free_sha256": sha256_file(m9b_truth_free), "seed": SEED,
    }
    save_json(output.parent / "truth-free-seal.json", seal)
    return seal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--m9b", type=Path, default=Path("artifacts/m9b/m9b-v1/truth-free.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/m10c/m10c-v2/truth-free.jsonl"))
    args = parser.parse_args()
    print(json.dumps(generate(args.data_dir, args.m9b, args.output), indent=2))


if __name__ == "__main__":
    main()

