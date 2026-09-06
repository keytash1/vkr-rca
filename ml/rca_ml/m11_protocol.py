"""Leakage guards, generic adapter contracts and statistics for M11."""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

DEVELOPMENT_ROLES = frozenset({"DEVELOPMENT_EXISTING", "DEVELOPMENT_AUXILIARY", "NEW_DEVELOPMENT"})
FORBIDDEN_SELECTION_ROLES = frozenset({"USED_TEST_READONLY", "USED_TEST", "LOCKED_NEW_TEST"})
FORBIDDEN_ADAPTER_KEYS = frozenset({
    "label", "root", "root_service", "ground_truth", "fault", "fault_type", "dataset", "system"
})


class MetricSource(Protocol):
    def metrics(self, incident_id: str) -> Sequence[dict]: ...


class TraceSource(Protocol):
    def traces(self, incident_id: str) -> Sequence[dict]: ...


class TopologySource(Protocol):
    def edges(self, incident_id: str) -> Sequence[dict]: ...


class IncidentSource(Protocol):
    def incident_ids(self) -> Sequence[str]: ...
    def candidate_services(self, incident_id: str) -> Sequence[str]: ...


def assert_truth_free_adapter_output(records: Iterable[dict]) -> None:
    """Reject truth and semantic dataset identity at the adapter boundary."""
    for record in records:
        leaked = FORBIDDEN_ADAPTER_KEYS & set(record)
        if leaked:
            raise ValueError(f"truth or semantic identity in adapter output: {sorted(leaked)}")


def assert_selection_ids_allowed(
    incident_ids: Iterable[str], dataset_by_incident: dict[str, str], roles: dict[str, str]
) -> None:
    """Fail closed if a model-building phase sees a used or locked test ID."""
    unknown = []
    forbidden = []
    for incident_id in incident_ids:
        dataset = dataset_by_incident.get(incident_id)
        if dataset is None or dataset not in roles:
            unknown.append(incident_id)
        elif roles[dataset] in FORBIDDEN_SELECTION_ROLES:
            forbidden.append(incident_id)
    if unknown:
        raise ValueError(f"unregistered incident IDs: {sorted(unknown)[:5]}")
    if forbidden:
        raise ValueError(f"used/locked test IDs reached model selection: {sorted(forbidden)[:5]}")


def transition_locked_test(ledger: dict, dataset: str) -> dict:
    """Apply the only legal, one-time and irreversible locked-test transition."""
    updated = copy.deepcopy(ledger)
    roles = updated["roles"]
    transitions = updated["locked_test_transition"]["transitions"]
    if roles.get(dataset) != "LOCKED_NEW_TEST":
        raise ValueError("dataset is not in LOCKED_NEW_TEST")
    if transitions:
        raise ValueError("locked test has already been opened")
    roles[dataset] = "USED_TEST"
    transitions.append({"dataset": dataset, "from": "LOCKED_NEW_TEST", "to": "USED_TEST"})
    return updated


def truth_rank(ranking: Sequence[dict]) -> int | None:
    for item in sorted(ranking, key=lambda value: int(value["rank"])):
        if int(item.get("label", 0)) == 1:
            return int(item["rank"])
    return None


def ranking_metrics(rankings: dict[str, list[dict]]) -> dict:
    """All-incident metrics. Missing truth is retained as a miss."""
    ranks = [truth_rank(ranking) for ranking in rankings.values()]
    denominator = len(ranks)
    result = {
        f"ac_at_{k}": sum(rank is not None and rank <= k for rank in ranks) / denominator
        if denominator else 0.0
        for k in (1, 2, 3, 5, 10)
    }
    result["mrr"] = (
        sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / denominator
        if denominator else 0.0
    )
    result["incidents"] = denominator
    result["root_observable"] = sum(rank is not None for rank in ranks)
    result["candidate_universe_coverage"] = (
        result["root_observable"] / denominator if denominator else 0.0
    )
    return result


def rank_histogram(rankings: dict[str, list[dict]]) -> dict[str, int]:
    def bucket(ranking: list[dict]) -> str:
        rank = truth_rank(ranking)
        if rank is None:
            return "not_in_candidate_universe"
        if rank <= 3:
            return f"rank_{rank}"
        if rank <= 5:
            return "rank_4_5"
        if rank <= 10:
            return "rank_6_10"
        return "rank_gt_10"

    counts = Counter(bucket(value) for value in rankings.values())
    order = ("rank_1", "rank_2", "rank_3", "rank_4_5", "rank_6_10", "rank_gt_10", "not_in_candidate_universe")
    return {name: counts[name] for name in order}


def oracle_ac_at_1(rankings: dict[str, list[dict]]) -> dict[str, float]:
    ranks = [truth_rank(value) for value in rankings.values()]
    denominator = len(ranks)
    return {
        str(k): sum(rank is not None and rank <= k for rank in ranks) / denominator
        if denominator else 0.0
        for k in (1, 2, 3, 5, 10)
    }


def error_decomposition(rankings: dict[str, list[dict]], k: int = 3) -> dict:
    stages = Counter()
    for ranking in rankings.values():
        rank = truth_rank(ranking)
        if rank is None:
            stages["ROOT_UNOBSERVABLE"] += 1
        elif rank == 1:
            stages["SUCCESS_AT_1"] += 1
        elif rank <= k:
            stages["WITHIN_K_ORDERING_FAILURE"] += 1
        else:
            stages["ROOT_BELOW_K"] += 1
    total = len(rankings)
    return {
        name: {"count": stages[name], "fraction": stages[name] / total if total else 0.0}
        for name in ("SUCCESS_AT_1", "WITHIN_K_ORDERING_FAILURE", "ROOT_BELOW_K", "ROOT_UNOBSERVABLE")
    }


def failure_taxonomy(
    base: dict[str, list[dict]],
    final: dict[str, list[dict]],
    profiles: dict[str, list[dict]],
) -> dict:
    """Classify every rank>1 case with an exclusive stage and overlapping causes."""
    primary = Counter()
    overlapping = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    errors = 0
    for incident in sorted(final):
        final_rank = truth_rank(final[incident])
        if final_rank == 1:
            continue
        errors += 1
        base_rank = truth_rank(base[incident])
        if base_rank is None:
            stage = "CANDIDATE_UNIVERSE_MISS"
        elif base_rank > 3:
            stage = "BELOW_TOP3"
        elif final_rank is not None and final_rank > 1:
            stage = "IN_TOP3_RERANK_ERROR"
        else:
            stage = "OTHER"
        primary[stage] += 1
        examples[stage].append(incident)

        incident_profiles = profiles.get(incident, [])
        root_service = next(
            (str(item["service"]) for item in base[incident] if int(item.get("label", 0)) == 1),
            None,
        )
        root_profile = next(
            (item for item in incident_profiles if item["service"] == root_service), None
        )
        metric_values = sorted(
            (float(item["components"]["MetricSupport"]) for item in incident_profiles),
            reverse=True,
        )
        matched_diagnostic = False
        if len(metric_values) >= 2 and metric_values[0] - metric_values[1] <= .05:
            overlapping["AMBIGUOUS_METRIC_EVIDENCE"] += 1
            matched_diagnostic = True
        if root_profile and float(root_profile["components"]["CoverageSupport"]) < .75:
            overlapping["MISSING_DOMINANT_MODALITY"] += 1
            matched_diagnostic = True
        if root_profile and float(root_profile["components"]["OODPenalty"]) > 0.0:
            overlapping["OOD_DOMAIN_SHIFT"] += 1
            matched_diagnostic = True
        if not matched_diagnostic:
            overlapping["OTHER"] += 1
    primary_order = ("CANDIDATE_UNIVERSE_MISS", "BELOW_TOP3", "IN_TOP3_RERANK_ERROR", "OTHER")
    overlap_order = ("AMBIGUOUS_METRIC_EVIDENCE", "MISSING_DOMINANT_MODALITY", "OOD_DOMAIN_SHIFT", "OTHER")
    return {
        "errors": errors,
        "primary_mutually_exclusive": {name: primary[name] for name in primary_order},
        "overlapping_diagnostics": {name: overlapping[name] for name in overlap_order},
        "examples": {name: values[:10] for name, values in examples.items()},
        "heuristic_limit": "Diagnostic overlap flags are descriptive thresholds, not causal labels.",
    }


def rerank_top_k(
    rankings: dict[str, list[dict]], predictions: dict[tuple[str, str], float], k: int
) -> dict[str, list[dict]]:
    """Reorder exactly the initial Top-K while preserving membership and tail order."""
    if k < 1:
        raise ValueError("k must be positive")
    result = {}
    for incident, original in rankings.items():
        ordered = sorted(original, key=lambda item: int(item["rank"]))
        effective_k = min(k, len(ordered))
        head, tail = ordered[:effective_k], ordered[effective_k:]
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
        final = [
            {**item, "evidence_reranker_score": predictions[(incident, str(item["service"]))]}
            for item in head
        ] + [dict(item) for item in tail]
        for rank, item in enumerate(final, 1):
            item["rank"] = rank
        if {str(item["service"]) for item in final[:effective_k]} != initial_head:
            raise AssertionError("Top-K membership changed")
        if [str(item["service"]) for item in final[effective_k:]] != initial_tail:
            raise AssertionError("tail ordering changed")
        result[incident] = final
    return result


def _metric_from_ranks(ranks: Sequence[int | None], metric: str) -> float:
    if not ranks:
        return 0.0
    if metric == "mrr":
        return float(np.mean([0.0 if rank is None else 1.0 / rank for rank in ranks]))
    if metric.startswith("ac_at_"):
        k = int(metric.removeprefix("ac_at_"))
        return float(np.mean([rank is not None and rank <= k for rank in ranks]))
    raise ValueError(f"unknown metric: {metric}")


def cluster_bootstrap(
    challenger: dict[str, list[dict]],
    baseline: dict[str, list[dict]],
    case_by_id: dict[str, dict],
    *,
    metric: str,
    resamples: int = 10_000,
    seed: int = 20260906,
) -> dict:
    """Paired bootstrap over (system, root_service, fault_type) clusters."""
    if set(challenger) != set(baseline):
        raise ValueError("paired bootstrap incident sets differ")
    clusters: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for incident in sorted(challenger):
        case = case_by_id[incident]
        key = (str(case["system"]), str(case["root"]), str(case["fault"]))
        clusters[key].append(incident)
    keys = sorted(clusters)
    if not keys:
        raise ValueError("cluster bootstrap requires incidents")
    rng = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        selected = rng.integers(0, len(keys), size=len(keys))
        incidents = [incident for position in selected for incident in clusters[keys[int(position)]]]
        c_ranks = [truth_rank(challenger[incident]) for incident in incidents]
        b_ranks = [truth_rank(baseline[incident]) for incident in incidents]
        deltas[index] = _metric_from_ranks(c_ranks, metric) - _metric_from_ranks(b_ranks, metric)
    observed = ranking_metrics(challenger)[metric] - ranking_metrics(baseline)[metric]
    low, high = np.quantile(deltas, [.025, .975])
    return {
        "metric": metric,
        "observed_delta": observed,
        "ci95": [float(low), float(high)],
        "clusters": len(keys),
        "resamples": resamples,
        "seed": seed,
        "supported_positive": bool(low > 0.0),
        "evidence_label": "SUPPORTED" if low > 0.0 else "WEAK_CLUSTER_NOT_SUPPORTED",
    }
