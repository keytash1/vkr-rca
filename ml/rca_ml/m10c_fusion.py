"""Leakage-safe rank fusion primitives for M10C modality experts."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

META_COLUMNS = (
    "metric_rank_percentile", "trace_rank_percentile",
    "metric_relative_score", "trace_relative_score",
    "expert_disagreement", "metric_margin", "trace_margin",
    "has_metrics", "has_traces", "has_topology",
    "metric_family_ratio", "trace_coverage", "candidate_count_log1p",
    "normalized_in_degree", "normalized_out_degree",
)


def rank_percentile(rank: int, count: int) -> float:
    return 1.0 if count <= 1 else 1.0 - (rank - 1) / (count - 1)


def relative_scores(ranking: list[dict]) -> dict[str, float]:
    scores = [float(item["score"]) for item in ranking]
    low, high = min(scores), max(scores)
    scale = high - low
    return {item["service"]: (float(item["score"]) - low) / scale if scale > 1e-12 else 0.5
            for item in ranking}


def build_meta_rows(metric_rankings: dict[str, list[dict]], trace_rankings: dict[str, list[dict]],
                    source_rows: list[dict]) -> list[dict]:
    source = {(row["incident_id"], row["service"]): row for row in source_rows}
    result = []
    if set(metric_rankings) != set(trace_rankings):
        raise ValueError("experts must predict identical incidents")
    for incident in sorted(metric_rankings):
        metric = metric_rankings[incident]
        trace = trace_rankings[incident]
        if {x["service"] for x in metric} != {x["service"] for x in trace}:
            raise ValueError("experts must rank identical candidate universes")
        mr = {item["service"]: int(item["rank"]) for item in metric}
        tr = {item["service"]: int(item["rank"]) for item in trace}
        ms, ts = relative_scores(metric), relative_scores(trace)
        mm = _top_margin(metric); tm = _top_margin(trace)
        count = len(metric)
        for item in metric:
            service = item["service"]
            row = source[(incident, service)]
            value = {
                "incident_id": incident, "service": service, "label": int(row["label"]),
                "metric_rank_percentile": rank_percentile(mr[service], count),
                "trace_rank_percentile": rank_percentile(tr[service], count),
                "metric_relative_score": ms[service], "trace_relative_score": ts[service],
                "expert_disagreement": abs(rank_percentile(mr[service], count) - rank_percentile(tr[service], count)),
                "metric_margin": mm if mr[service] == 1 else 0.0,
                "trace_margin": tm if tr[service] == 1 else 0.0,
                "has_metrics": float(row["coverage_has_metrics"]),
                "has_traces": float(row["coverage_has_traces"]),
                "has_topology": float(row["coverage_has_topology"]),
                "metric_family_ratio": float(row["coverage_metric_family_ratio"]),
                "trace_coverage": float(row["trace_trace_coverage"]),
                "candidate_count_log1p": float(np.log1p(count)),
                "normalized_in_degree": float(row["topology_normalized_in_degree"]),
                "normalized_out_degree": float(row["topology_normalized_out_degree"]),
            }
            result.append(value)
    return result


def simple_fusion(metric_rankings: dict[str, list[dict]], trace_rankings: dict[str, list[dict]],
                  method: str) -> dict[str, list[dict]]:
    result = {}
    for incident in sorted(metric_rankings):
        first, second = metric_rankings[incident], trace_rankings[incident]
        count = len(first)
        by_service = {item["service"]: item for item in first}
        ranks_a = {item["service"]: item["rank"] for item in first}
        ranks_b = {item["service"]: item["rank"] for item in second}
        values = []
        for service in sorted(by_service):
            if method == "rank_average":
                score = (rank_percentile(ranks_a[service], count) + rank_percentile(ranks_b[service], count)) / 2
            elif method == "rrf":
                score = 1 / (60 + ranks_a[service]) + 1 / (60 + ranks_b[service])
            else:
                raise ValueError(f"unknown fusion method {method}")
            values.append({"service": service, "score": score, "label": by_service[service]["label"]})
        values.sort(key=lambda item: (-item["score"], item["service"]))
        for rank, item in enumerate(values, 1): item["rank"] = rank
        result[incident] = values
    return result


def assert_oof_predictions(oof_rows: list[dict], training_by_incident: dict[str, set[str]]) -> None:
    for row in oof_rows:
        if row["incident_id"] in training_by_incident.get(row["incident_id"], set()):
            raise ValueError("in-sample expert prediction reached meta training")
        if not row.get("expert_train_incidents"):
            raise ValueError("OOF provenance is missing")
        if row["incident_id"] in row["expert_train_incidents"]:
            raise ValueError("OOF provenance contains predicted incident")


def _top_margin(ranking: list[dict]) -> float:
    if len(ranking) < 2:
        return 1.0
    ordered = sorted((float(item["score"]) for item in ranking), reverse=True)
    scale = max(abs(ordered[0]), abs(ordered[1]), 1e-9)
    return (ordered[0] - ordered[1]) / scale

