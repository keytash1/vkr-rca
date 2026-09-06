"""Promoted Evidence-Aware Top-3 Reranker for the M10D integration.

This module deliberately exposes only truth-free evidence feature extraction
and frozen Top-3 reranking.  The research-only deterministic verifier statuses
and abstention policy from M10D-B are not part of the integration API.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import xgboost as xgb

from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_FAMILIES

TOP_K = 3
SEEDS = (20260906, 20260907, 20260908, 20260909, 20260910)
COMPONENTS = (
    "MetricSupport",
    "TraceLocalSupport",
    "PropagationSupport",
    "TopologySupport",
    "DependencyWaitSupport",
    "CoverageSupport",
    "ContradictionEvidence",
    "OODPenalty",
    "ExpertAgreement",
)
RANKING_CONTEXT_FEATURES = (
    "base_rank_percentile",
    "base_relative_score",
    "base_margin",
)
EVIDENCE_FEATURES = (
    *(f"component_{name}" for name in COMPONENTS),
    "support_score",
)
RERANKER_FEATURES = (*EVIDENCE_FEATURES, *RANKING_CONTEXT_FEATURES)
FORBIDDEN_INFERENCE_KEYS = frozenset({
    "label",
    "root",
    "root_service",
    "ground_truth",
    "fault",
    "system",
    "dataset",
})


def assert_truth_free(items: Iterable[dict]) -> None:
    """Reject target and semantic-identity fields at the inference boundary."""
    for item in items:
        leaked = FORBIDDEN_INFERENCE_KEYS & set(item)
        if leaked:
            raise ValueError(
                f"truth or semantic identity reached reranker inference: {sorted(leaked)}"
            )


def fit_ood_stats(rows: Sequence[dict], incident_ids: Sequence[str]) -> dict:
    """Fit robust development-only bounds used by the OOD evidence feature."""
    wanted = set(incident_ids)
    selected = [row for row in rows if row["incident_id"] in wanted]
    if not selected:
        raise ValueError("OOD fit requires development rows")
    stats = {}
    for name in FEATURE_COLUMNS_M10C:
        values = np.asarray([float(row.get(name, 0.0)) for row in selected], dtype=float)
        stats[name] = {
            "median": float(np.median(values)),
            "iqr": max(float(np.quantile(values, .75) - np.quantile(values, .25)), 1e-9),
            "low": float(np.quantile(values, .01)),
            "high": float(np.quantile(values, .99)),
        }
    return stats


def build_evidence_features(
    rows: Sequence[dict],
    ranking: Sequence[dict],
    *,
    metric_ranking: Sequence[dict] | None = None,
    trace_ranking: Sequence[dict] | None = None,
    ood_stats: dict | None = None,
    top_k: int = TOP_K,
) -> list[dict]:
    """Build the promoted truth-free evidence features for the initial Top-K."""
    assert_truth_free(rows)
    assert_truth_free(ranking)
    if metric_ranking is not None:
        assert_truth_free(metric_ranking)
    if trace_ranking is not None:
        assert_truth_free(trace_ranking)

    by_service = {str(row["service"]): row for row in rows}
    ordered = sorted(ranking, key=lambda item: (int(item["rank"]), str(item["service"])))
    if not ordered or any(str(item["service"]) not in by_service for item in ordered):
        raise ValueError("ranking and evidence candidate universes differ")

    local_support = {service: _trace_local_support(row) for service, row in by_service.items()}
    strongest_other = {
        service: max((value for name, value in local_support.items() if name != service), default=0.0)
        for service in by_service
    }
    metric_positions = _rank_percentiles(metric_ranking or ordered)
    trace_positions = _rank_percentiles(trace_ranking or ordered)
    output = []
    for item in ordered[:max(1, top_k)]:
        service = str(item["service"])
        row = by_service[service]
        metric = _metric_support(row)
        trace_local = local_support[service]
        propagation = _propagation_support(row)
        topology = _topology_support(row, propagation)
        dependency = _dependency_wait_support(row, trace_local)
        coverage = _coverage_support(row)
        agreement = (
            1.0 - abs(metric_positions[service] - trace_positions[service])
            if float(row.get("coverage_has_metrics", 0.0)) > 0
            and float(row.get("coverage_has_traces", 0.0)) > 0
            else .5
        )
        contradiction = _contradiction(
            row, metric, trace_local, propagation, strongest_other[service]
        )
        components = {
            "MetricSupport": metric,
            "TraceLocalSupport": trace_local,
            "PropagationSupport": propagation,
            "TopologySupport": topology,
            "DependencyWaitSupport": dependency,
            "CoverageSupport": coverage,
            "ContradictionEvidence": contradiction,
            "OODPenalty": _ood_penalty(row, ood_stats),
            "ExpertAgreement": agreement,
        }
        output.append({
            "service": service,
            "base_rank": int(item["rank"]),
            "base_score": float(item["score"]),
            "components": components,
            "support_score": _support_score(components),
        })
    return output


def build_reranker_records(
    incident_id: str,
    profiles: Sequence[dict],
    ranking: Sequence[dict],
) -> list[dict]:
    """Convert evidence profiles into the exact frozen 13-feature schema."""
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    count = len(ordered)
    scores = [float(item["score"]) for item in ordered]
    low, high = min(scores), max(scores)
    scale = high - low
    margin = (
        1.0
        if count == 1
        else (scores[0] - scores[1]) / max(abs(scores[0]), abs(scores[1]), 1e-9)
    )
    records = []
    for profile in profiles:
        record = {
            "incident_id": incident_id,
            "service": profile["service"],
            **{
                f"component_{name}": float(profile["components"][name])
                for name in COMPONENTS
            },
            "support_score": float(profile["support_score"]),
            "base_rank_percentile": (
                1.0
                if count == 1
                else 1.0 - (int(profile["base_rank"]) - 1) / (count - 1)
            ),
            "base_relative_score": (
                .5
                if scale <= 1e-12
                else (float(profile["base_score"]) - low) / scale
            ),
            "base_margin": margin if int(profile["base_rank"]) == 1 else 0.0,
        }
        if tuple(name for name in record if name in RERANKER_FEATURES) != RERANKER_FEATURES:
            raise ValueError("reranker feature schema mismatch")
        records.append(record)
    return records


def load_frozen_models(model_dir: Path) -> list[xgb.Booster]:
    models = []
    for seed in SEEDS:
        model = xgb.Booster()
        model.load_model(model_dir / f"reranker-seed-{seed}.json")
        if tuple(model.feature_names or ()) != RERANKER_FEATURES:
            raise ValueError("frozen reranker model schema mismatch")
        models.append(model)
    return models


def predict_ensemble(models: Sequence[xgb.Booster], records: Sequence[dict]) -> dict[tuple[str, str], float]:
    if not models:
        raise ValueError("reranker ensemble is empty")
    matrix = np.asarray(
        [[float(item[name]) for name in RERANKER_FEATURES] for item in records],
        dtype=np.float32,
    )
    data = xgb.DMatrix(matrix, feature_names=list(RERANKER_FEATURES))
    predictions = [model.predict(data) for model in models]
    mean = np.mean(np.asarray(predictions, dtype=float), axis=0)
    return {
        (str(item["incident_id"]), str(item["service"])): float(value)
        for item, value in zip(records, mean, strict=True)
    }


def rerank_top3(
    rankings: dict[str, list[dict]],
    predictions: dict[tuple[str, str], float],
) -> dict[str, list[dict]]:
    """Reorder only the initial Top-3; preserve its membership and the tail."""
    result = {}
    for incident, original in rankings.items():
        ordered = sorted(original, key=lambda item: int(item["rank"]))
        head, tail = ordered[:TOP_K], ordered[TOP_K:]
        initial_head = {str(item["service"]) for item in head}
        initial_tail = [str(item["service"]) for item in tail]
        head = sorted(
            head,
            key=lambda item: (
                -predictions[(incident, str(item["service"]))],
                int(item["rank"]),
                str(item["service"]),
            ),
        )
        reranked = [
            {**item, "evidence_reranker_score": predictions[(incident, str(item["service"]))]}
            for item in head
        ] + [dict(item) for item in tail]
        for rank, item in enumerate(reranked, 1):
            item["rank"] = rank
        if {str(item["service"]) for item in reranked[:TOP_K]} != initial_head:
            raise AssertionError("Top-3 membership changed")
        if [str(item["service"]) for item in reranked[TOP_K:]] != initial_tail:
            raise AssertionError("tail ordering changed")
        result[incident] = reranked
    return result


def _ood_penalty(row: dict, stats: dict | None) -> float:
    if not stats:
        return 0.0
    outside = sum(
        float(row.get(name, 0.0)) < value["low"]
        or float(row.get(name, 0.0)) > value["high"]
        for name, value in stats.items()
    )
    return outside / len(stats)


def _metric_support(row: dict) -> float:
    families = []
    residual = max(
        float(row.get("workload_residual_persistence", 0.0)),
        _bounded_shift(float(row.get("workload_residual_location", 0.0))),
        _bounded_shift(float(row.get("workload_residual_p90", 0.0))),
        _bounded_shift(float(row.get("workload_residual_peak", 0.0))),
    )
    for family in METRIC_FAMILIES:
        if float(row.get(f"metric_{family}_has", 0.0)) <= 0:
            continue
        value = _clip(
            .45 * float(row.get(f"metric_{family}_max_shift_percentile", .5))
            + .35 * float(row.get(f"metric_{family}_persistence", 0.0))
            + .20 * _bounded_shift(float(row.get(f"metric_{family}_max_shift", 0.0)))
        )
        if family == "traffic_rate":
            value = _clip(.7 * value + .3 * residual)
        families.append(value)
    return float(np.mean(sorted(families, reverse=True)[:2])) if families else 0.0


def _trace_local_support(row: dict) -> float:
    if float(row.get("coverage_has_traces", row.get("has_trace", 0.0))) <= 0:
        return 0.0
    anomaly = max(
        float(row.get("trace_local_evidence", 0.0)),
        float(row.get("trace_latency_strength", 0.0)),
        float(row.get("trace_error_strength", 0.0)),
    )
    percentile = max(
        float(row.get("trace_latency_z_log1p_percentile", .5)),
        float(row.get("trace_error_z_log1p_percentile", .5)),
    )
    return _clip(
        .35 * anomaly
        + .20 * percentile
        + .30 * float(row.get("trace_median_exclusive_ratio", 0.0))
        + .15 * float(row.get("trace_log1p_median_exclusive_duration_ms_percentile", .5))
    )


def _propagation_support(row: dict) -> float:
    if float(row.get("coverage_has_topology", row.get("trace_topology_source_active", 0.0))) <= 0:
        return 0.0
    precision = float(row.get("trace_topology_precision", 0.0))
    recall = float(row.get("trace_topology_recall", 0.0))
    f1 = float(row.get("trace_topology_f1", 0.0))
    unexpected = max(
        0.0,
        float(row.get("trace_observed_anomaly_ratio", 0.0))
        - float(row.get("trace_expected_affected_ratio", 0.0)),
    )
    return _clip(.25 * precision + .25 * recall + .35 * f1 + .15 * (1.0 - unexpected))


def _topology_support(row: dict, propagation: float) -> float:
    if float(row.get("coverage_has_topology", 0.0)) <= 0:
        return 0.0
    region_fit = 1.0 - abs(
        float(row.get("trace_expected_affected_ratio", 0.0))
        - float(row.get("trace_observed_anomaly_ratio", 0.0))
    )
    return _clip(
        .50 * float(row.get("trace_topology_f1", propagation))
        + .30 * float(row.get("topology_active_trace_coverage", 0.0))
        + .20 * region_fit
    )


def _dependency_wait_support(row: dict, local_support: float) -> float:
    if float(row.get("coverage_has_traces", 0.0)) <= 0:
        return 0.0
    return _clip(
        .45 * (1.0 - float(row.get("trace_median_downstream_wait_ratio", 0.0)))
        + .35 * float(row.get("trace_median_exclusive_ratio", 0.0))
        + .20 * local_support
    )


def _coverage_support(row: dict) -> float:
    modalities = (
        float(row.get("coverage_has_metrics", 0.0)),
        float(row.get("coverage_has_traces", 0.0)),
        float(row.get("coverage_has_topology", 0.0)),
    )
    return _clip(
        .55 * max(modalities)
        + .20 * float(row.get("coverage_metric_family_ratio", 0.0))
        + .15 * float(row.get("coverage_trace_fraction", 0.0))
        + .10 * float(row.get("topology_active_trace_coverage", 0.0))
    )


def _contradiction(
    row: dict,
    metric: float,
    trace_local: float,
    propagation: float,
    strongest_other_local: float,
) -> float:
    values = []
    if float(row.get("coverage_has_metrics", 0.0)) > 0 and metric < .30:
        values.append(.55)
    if float(row.get("coverage_has_traces", 0.0)) > 0:
        wait = float(row.get("trace_median_downstream_wait_ratio", 0.0))
        if wait > .70 and trace_local < strongest_other_local:
            values.append(_clip(wait))
        if strongest_other_local - trace_local > .35:
            values.append(_clip(strongest_other_local - trace_local))
    if float(row.get("coverage_has_topology", 0.0)) > 0 and propagation < .30:
        values.append(_clip(1.0 - propagation))
    return max(values) if values else 0.0


def _support_score(components: dict) -> float:
    positive = (
        .30 * components["MetricSupport"]
        + .20 * components["TraceLocalSupport"]
        + .15 * components["PropagationSupport"]
        + .10 * components["TopologySupport"]
        + .10 * components["DependencyWaitSupport"]
        + .10 * components["CoverageSupport"]
        + .05 * components["ExpertAgreement"]
    )
    return _clip(
        positive
        - .35 * components["ContradictionEvidence"]
        - .10 * components["OODPenalty"]
    )


def _rank_percentiles(ranking: Sequence[dict]) -> dict[str, float]:
    ordered = sorted(ranking, key=lambda item: (int(item["rank"]), str(item["service"])))
    count = len(ordered)
    return {
        str(item["service"]): (
            1.0 if count <= 1 else 1.0 - (int(item["rank"]) - 1) / (count - 1)
        )
        for item in ordered
    }


def _bounded_shift(value: float) -> float:
    return _clip(math.log1p(max(0.0, abs(value))) / math.log(21.0))


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
