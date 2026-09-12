"""Leakage-resistant splitting and evaluation primitives for M13."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence

import numpy as np

SEED = 20260906
KS = (1, 2, 3, 5, 10)


def cluster_key(item: dict) -> tuple[str, ...]:
    return tuple(str(item.get(name, "")) for name in (
        "system", "root_service", "fault_family", "workload_regime", "intensity",
    ))


def grouped_folds(cases: Sequence[dict], folds: int = 5, seed: int = SEED) -> dict[str, int]:
    """Assign complete repetition clusters to deterministic, balanced folds."""
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for item in cases:
        groups[cluster_key(item)].append(str(item["incident_id"]))
    ordered = sorted(
        groups,
        key=lambda key: hashlib.sha256(f"{seed}:{key}".encode()).hexdigest(),
    )
    assignments = {}
    loads = [0] * folds
    for key in ordered:
        fold = min(range(folds), key=lambda value: (loads[value], value))
        for incident_id in groups[key]:
            assignments[incident_id] = fold
        loads[fold] += len(groups[key])
    return assignments


def held_out_group_folds(cases: Sequence[dict], field: str) -> dict[str, str]:
    return {str(item["incident_id"]): str(item[field]) for item in cases}


def truth_rank(ranking: Sequence[dict], root_service: str) -> int | None:
    ordered = sorted(ranking, key=lambda item: int(item.get("rank", 10**9)))
    return next((index for index, item in enumerate(ordered, 1) if item["service"] == root_service), None)


def ranking_metrics(rankings: dict[str, list[dict]], truth: dict[str, dict]) -> dict:
    ids = sorted(truth)
    ranks = [truth_rank(rankings[incident], truth[incident]["root_service"]) for incident in ids]
    result = {
        f"ac_at_{k}": float(np.mean([rank is not None and rank <= k for rank in ranks]))
        for k in KS
    }
    result.update({
        "mrr": float(np.mean([0.0 if rank is None else 1.0 / rank for rank in ranks])),
        "candidate_universe_coverage": float(np.mean([rank is not None for rank in ranks])),
        "incidents": len(ids),
        "absolute_wilson_95": {
            f"ac_at_{k}": wilson(sum(rank is not None and rank <= k for rank in ranks), len(ranks))
            for k in KS
        },
    })
    return result


def wilson(successes: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    z, p = 1.959963984540054, successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [centre - margin, centre + margin]


def paired_bootstrap(
    challenger: dict[str, list[dict]],
    baseline: dict[str, list[dict]],
    truth: dict[str, dict],
    metric: str,
    *,
    cluster: bool,
    resamples: int = 10_000,
    seed: int = SEED,
) -> dict:
    if set(challenger) != set(baseline) or set(challenger) != set(truth):
        raise ValueError("paired comparison requires identical incident denominators")
    groups: dict[tuple[str, ...] | str, list[str]] = defaultdict(list)
    for incident_id, item in truth.items():
        groups[cluster_key(item) if cluster else incident_id].append(incident_id)
    keys = sorted(groups, key=str)
    if not keys:
        raise ValueError("bootstrap requires incidents")
    randomizer = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sampled = randomizer.integers(0, len(keys), len(keys))
        ids = [incident_id for position in sampled for incident_id in groups[keys[int(position)]]]
        deltas[index] = _metric(challenger, truth, ids, metric) - _metric(baseline, truth, ids, metric)
    ids = sorted(truth)
    low, high = np.quantile(deltas, [.025, .975])
    return {
        "observed_delta": _metric(challenger, truth, ids, metric) - _metric(baseline, truth, ids, metric),
        "ci95": [float(low), float(high)],
        "resamples": resamples,
        "seed": seed,
        "unit": "cluster" if cluster else "incident",
        "groups": len(keys),
        "supported_positive": bool(low > 0),
    }


def deterministic_chance(incident_id: str, services: Sequence[str], seed: int = SEED) -> list[dict]:
    scored = [
        {
            "service": service,
            "score": int.from_bytes(hashlib.sha256(f"{seed}:{incident_id}:{service}".encode()).digest()[:8], "big") / 2**64,
        }
        for service in sorted(set(map(str, services)))
    ]
    return _rank(scored)


def rank_scores(scores: dict[str, float]) -> list[dict]:
    return _rank([{"service": service, "score": float(score)} for service, score in scores.items()])


def assert_selection_ids_allowed(incident_ids: Sequence[str]) -> None:
    forbidden = [value for value in incident_ids if value.startswith("m12-") or "astronomy" in value.lower()]
    if forbidden:
        raise ValueError(f"non-development incident IDs at M13 selection boundary: {forbidden[:3]}")


def _rank(items: list[dict]) -> list[dict]:
    output = sorted(items, key=lambda item: (-float(item["score"]), str(item["service"])))
    for rank, item in enumerate(output, 1):
        item["rank"] = rank
    return output


def _metric(rankings: dict[str, list[dict]], truth: dict[str, dict], ids: Sequence[str], metric: str) -> float:
    ranks = [truth_rank(rankings[incident], truth[incident]["root_service"]) for incident in ids]
    if metric == "mrr":
        return float(np.mean([0.0 if rank is None else 1.0 / rank for rank in ranks]))
    k = int(metric.removeprefix("ac_at_"))
    return float(np.mean([rank is not None and rank <= k for rank in ranks]))
