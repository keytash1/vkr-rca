"""Truth-free diagnostic evidence verification for M10D-B.

The ranker and verifier intentionally answer different questions.  The ranker
orders candidates; this module summarizes whether the telemetry available for
each candidate supports that hypothesis.  Ground truth is accepted only by
the calibration/evaluation helpers, never by evidence construction.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from .m10c_schema import FEATURE_COLUMNS_M10C, METRIC_FAMILIES

SEED = 20260906
STATUSES = ("VERIFIED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "CONTRADICTED")
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
FORBIDDEN_INFERENCE_KEYS = frozenset({
    "label", "root", "root_service", "ground_truth", "fault", "system", "dataset",
})

DEFAULT_STATUS_POLICY = {
    "verified_support": 0.65,
    "partial_support": 0.40,
    "contradiction": 0.55,
    "minimum_coverage": 0.25,
}


def assert_truth_free(items: Iterable[dict]) -> None:
    """Reject labels and semantic identity before verifier inference."""
    for item in items:
        leaked = FORBIDDEN_INFERENCE_KEYS & set(item)
        if leaked:
            raise ValueError(f"truth or semantic identity reached verifier inference: {sorted(leaked)}")


def fit_ood_stats(rows: Sequence[dict], incident_ids: Sequence[str]) -> dict:
    """Fit robust bounds on development rows only."""
    wanted = set(incident_ids)
    selected = [row for row in rows if row["incident_id"] in wanted]
    if not selected:
        raise ValueError("OOD fit requires development rows")
    stats = {}
    for name in FEATURE_COLUMNS_M10C:
        values = np.asarray([float(row.get(name, 0.0)) for row in selected], dtype=float)
        median = float(np.median(values))
        iqr = float(np.quantile(values, .75) - np.quantile(values, .25))
        stats[name] = {
            "median": median,
            "iqr": max(iqr, 1e-9),
            "low": float(np.quantile(values, .01)),
            "high": float(np.quantile(values, .99)),
        }
    return stats


def ood_penalty(row: dict, stats: dict | None) -> float:
    if not stats:
        return 0.0
    outside = sum(
        float(row.get(name, 0.0)) < value["low"] or float(row.get(name, 0.0)) > value["high"]
        for name, value in stats.items()
    )
    return outside / len(stats)


def build_evidence_profiles(
    rows: Sequence[dict],
    ranking: Sequence[dict],
    *,
    metric_ranking: Sequence[dict] | None = None,
    trace_ranking: Sequence[dict] | None = None,
    ood_stats: dict | None = None,
    top_k: int = 3,
    policy: dict | None = None,
) -> list[dict]:
    """Build deterministic evidence profiles for the ranker's Top-K.

    `rows` may contain the frozen M10C vector plus truth-free legacy topology
    summaries.  Ranking items may contain only service/score/rank.  The
    function never reads correctness labels.
    """
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
        metric, dominant = _metric_support(row)
        trace_local = local_support[service]
        propagation, propagation_detail = _propagation_support(row)
        topology = _topology_support(row, propagation_detail)
        dependency = _dependency_wait_support(row, trace_local)
        coverage = _coverage_support(row)
        # A missing expert is neutral.  Using its tied, lexicographically
        # ordered ranks would turn a service-name tie break into an accidental
        # learned feature.
        agreement = (
            1.0 - abs(metric_positions[service] - trace_positions[service])
            if float(row.get("coverage_has_metrics", 0.0)) > 0
            and float(row.get("coverage_has_traces", 0.0)) > 0
            else .5
        )
        contradiction, contradiction_reasons = _contradiction(
            row, metric, trace_local, propagation, strongest_other[service]
        )
        ood = ood_penalty(row, ood_stats)
        components = {
            "MetricSupport": metric,
            "TraceLocalSupport": trace_local,
            "PropagationSupport": propagation,
            "TopologySupport": topology,
            "DependencyWaitSupport": dependency,
            "CoverageSupport": coverage,
            "ContradictionEvidence": contradiction,
            "OODPenalty": ood,
            "ExpertAgreement": agreement,
        }
        support = _support_score(components)
        profile = {
            "service": service,
            "base_rank": int(item["rank"]),
            "base_score": float(item["score"]),
            "components": components,
            "support_score": support,
            "dominant_metric_families": dominant,
            "coverage_detail": {
                "has_metrics": bool(row.get("coverage_has_metrics", 0.0)),
                "has_traces": bool(row.get("coverage_has_traces", 0.0)),
                "has_topology": bool(row.get("coverage_has_topology", 0.0)),
                "metric_family_ratio": float(row.get("coverage_metric_family_ratio", 0.0)),
                "trace_fraction": float(row.get("coverage_trace_fraction", 0.0)),
            },
            "propagation_detail": propagation_detail,
            "contradictions": contradiction_reasons,
            "status": status_for(components, support, policy or DEFAULT_STATUS_POLICY),
            "claim_scope": "diagnostic evidence support; not causal proof",
        }
        output.append(profile)
    return output


def status_for(components: dict, support_score: float, policy: dict) -> str:
    coverage = float(components["CoverageSupport"])
    contradiction = float(components["ContradictionEvidence"])
    if coverage < float(policy["minimum_coverage"]):
        return "INSUFFICIENT_EVIDENCE"
    if contradiction >= float(policy["contradiction"]):
        return "CONTRADICTED"
    if support_score >= float(policy["verified_support"]):
        return "VERIFIED"
    if support_score >= float(policy["partial_support"]):
        return "PARTIALLY_SUPPORTED"
    return "INSUFFICIENT_EVIDENCE"


def calibrate_status_policy(records: Sequence[dict]) -> dict:
    """Select interpretable status cutoffs from labeled development records."""
    if not records:
        raise ValueError("status calibration requires development records")
    candidates = []
    for verified in (.55, .65, .75):
        for partial in (.30, .40, .50):
            if partial >= verified:
                continue
            for contradiction in (.40, .55, .70):
                for coverage in (.20, .35, .50):
                    policy = {
                        "verified_support": verified,
                        "partial_support": partial,
                        "contradiction": contradiction,
                        "minimum_coverage": coverage,
                    }
                    summary = evaluate_statuses(records, policy)
                    verified_ok = summary["verified_cases"] >= 5 and summary["verified_precision"] >= .80
                    contradicted_ok = (
                        summary["contradicted_cases"] >= 5
                        and summary["contradicted_error_precision"] >= .60
                    )
                    feasible = verified_ok and contradicted_ok
                    objective = (
                        .45 * summary["verified_precision"]
                        + .35 * summary["contradicted_error_precision"]
                        + .10 * summary["verified_coverage"]
                        + .10 * summary["contradicted_coverage"]
                    )
                    candidates.append((feasible, objective, summary["decisive_coverage"], policy, summary))
    feasible = [value for value in candidates if value[0]]
    selected = max(feasible or candidates, key=lambda value: (value[1], value[2], -value[3]["verified_support"]))
    return {
        **selected[3],
        "selection": "development_only_grid",
        "feasible_precision_constraints": bool(selected[0]),
        "calibration_summary": selected[4],
    }


def evaluate_statuses(records: Sequence[dict], policy: dict) -> dict:
    statuses = []
    for record in records:
        components = record["components"]
        status = status_for(components, float(record["support_score"]), policy)
        statuses.append((status, bool(record["correct"])))
    verified = [correct for status, correct in statuses if status == "VERIFIED"]
    contradicted = [correct for status, correct in statuses if status == "CONTRADICTED"]
    count = len(statuses)
    return {
        "cases": count,
        "base_accuracy": float(np.mean([correct for _, correct in statuses])),
        "verified_cases": len(verified),
        "verified_coverage": len(verified) / count,
        "verified_precision": float(np.mean(verified)) if verified else 0.0,
        "contradicted_cases": len(contradicted),
        "contradicted_coverage": len(contradicted) / count,
        "contradicted_error_precision": float(np.mean([not value for value in contradicted])) if contradicted else 0.0,
        "decisive_coverage": (len(verified) + len(contradicted)) / count,
        "status_counts": {status: sum(value == status for value, _ in statuses) for status in STATUSES},
    }


def evaluate_abstention(records: Sequence[dict], policy: dict, accepted_statuses: Sequence[str]) -> dict:
    accepted_set = set(accepted_statuses)
    accepted = []
    for record in records:
        status = status_for(record["components"], float(record["support_score"]), policy)
        if status in accepted_set:
            accepted.append(record)
    return {
        "cases": len(records),
        "accepted": len(accepted),
        "coverage": len(accepted) / len(records) if records else 0.0,
        "selective_ac_at_1": float(np.mean([item["correct"] for item in accepted])) if accepted else None,
        "selective_mrr": float(np.mean([1 / int(item["truth_rank"]) for item in accepted])) if accepted else None,
        "rule": {"accepted_statuses": list(accepted_statuses)},
    }


def _metric_support(row: dict) -> tuple[float, list[dict]]:
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
        percentile = float(row.get(f"metric_{family}_max_shift_percentile", .5))
        persistence = float(row.get(f"metric_{family}_persistence", 0.0))
        shift = _bounded_shift(float(row.get(f"metric_{family}_max_shift", 0.0)))
        value = _clip(.45 * percentile + .35 * persistence + .20 * shift)
        if family == "traffic_rate":
            value = _clip(.7 * value + .3 * residual)
        families.append({"family": family, "support": value})
    families.sort(key=lambda item: (-item["support"], item["family"]))
    if not families:
        return 0.0, []
    score = float(np.mean([item["support"] for item in families[:2]]))
    return score, families[:3]


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
    exclusive = float(row.get("trace_median_exclusive_ratio", 0.0))
    duration = float(row.get("trace_log1p_median_exclusive_duration_ms_percentile", .5))
    return _clip(.35 * anomaly + .20 * percentile + .30 * exclusive + .15 * duration)


def _propagation_support(row: dict) -> tuple[float, dict]:
    if float(row.get("coverage_has_topology", row.get("trace_topology_source_active", 0.0))) <= 0:
        detail = {
            "precision_consistency": 0.0,
            "recall_consistency": 0.0,
            "f1_consistency": 0.0,
            "weighted_graph_distance_proxy": 1.0,
            "affected_ancestor_fraction": 0.0,
            "unexpected_downstream_anomaly_fraction_proxy": 0.0,
        }
        return 0.0, detail
    precision = float(row.get("trace_topology_precision", 0.0))
    recall = float(row.get("trace_topology_recall", 0.0))
    f1 = float(row.get("trace_topology_f1", 0.0))
    ancestors = float(row.get("topology_ancestor_ratio", row.get("trace_ancestor_ratio", 0.0)))
    observed = float(row.get("trace_observed_anomaly_ratio", 0.0))
    expected = float(row.get("trace_expected_affected_ratio", 0.0))
    unexpected = max(0.0, observed - expected)
    detail = {
        "precision_consistency": _clip(precision),
        "recall_consistency": _clip(recall),
        "f1_consistency": _clip(f1),
        "weighted_graph_distance_proxy": _clip(1.0 - f1),
        "affected_ancestor_fraction": _clip(ancestors),
        "unexpected_downstream_anomaly_fraction_proxy": _clip(unexpected),
    }
    return _clip(.25 * precision + .25 * recall + .35 * f1 + .15 * (1.0 - unexpected)), detail


def _topology_support(row: dict, detail: dict) -> float:
    if float(row.get("coverage_has_topology", 0.0)) <= 0:
        return 0.0
    active = float(row.get("topology_active_trace_coverage", 0.0))
    region_fit = 1.0 - abs(
        float(row.get("trace_expected_affected_ratio", 0.0))
        - float(row.get("trace_observed_anomaly_ratio", 0.0))
    )
    return _clip(.50 * detail["f1_consistency"] + .30 * active + .20 * region_fit)


def _dependency_wait_support(row: dict, local_support: float) -> float:
    if float(row.get("coverage_has_traces", 0.0)) <= 0:
        return 0.0
    wait = float(row.get("trace_median_downstream_wait_ratio", 0.0))
    exclusive = float(row.get("trace_median_exclusive_ratio", 0.0))
    return _clip(.45 * (1.0 - wait) + .35 * exclusive + .20 * local_support)


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


def _contradiction(row: dict, metric: float, trace_local: float, propagation: float,
                   strongest_other_local: float) -> tuple[float, list[str]]:
    reasons = []
    values = []
    if float(row.get("coverage_has_metrics", 0.0)) > 0 and metric < .30:
        values.append(.55)
        reasons.append("candidate metrics are available but weak")
    if float(row.get("coverage_has_traces", 0.0)) > 0:
        wait = float(row.get("trace_median_downstream_wait_ratio", 0.0))
        if wait > .70 and trace_local < strongest_other_local:
            values.append(_clip(wait))
            reasons.append("candidate mostly waits downstream while another service has stronger local evidence")
        if strongest_other_local - trace_local > .35:
            values.append(_clip(strongest_other_local - trace_local))
            reasons.append("another service has substantially stronger local trace evidence")
    if float(row.get("coverage_has_topology", 0.0)) > 0 and propagation < .30:
        values.append(_clip(1.0 - propagation))
        reasons.append("candidate topology does not explain the observed symptom region")
    return (max(values) if values else 0.0), reasons


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
    return _clip(positive - .35 * components["ContradictionEvidence"] - .10 * components["OODPenalty"])


def _rank_percentiles(ranking: Sequence[dict]) -> dict[str, float]:
    ordered = sorted(ranking, key=lambda item: (int(item["rank"]), str(item["service"])))
    count = len(ordered)
    return {
        str(item["service"]): 1.0 if count <= 1 else 1.0 - (int(item["rank"]) - 1) / (count - 1)
        for item in ordered
    }


def _bounded_shift(value: float) -> float:
    return _clip(math.log1p(max(0.0, abs(value))) / math.log(21.0))


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
