"""Incident-level ranking metrics and deterministic paired bootstrap."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence


def rank_metrics(ranks: Iterable[int], *, total: int | None = None) -> dict[str, float]:
    values = list(ranks)
    denominator = total if total is not None else len(values)
    if denominator <= 0:
        return {name: 0.0 for name in ("ac_at_1", "ac_at_3", "mrr", "ndcg_at_1", "ndcg_at_3")}
    return {
        "ac_at_1": sum(rank == 1 for rank in values) / denominator,
        "ac_at_3": sum(0 < rank <= 3 for rank in values) / denominator,
        "mrr": sum(1.0 / rank for rank in values if rank > 0) / denominator,
        "ndcg_at_1": sum(_ndcg(rank, 1) for rank in values) / denominator,
        "ndcg_at_3": sum(_ndcg(rank, 3) for rank in values) / denominator,
    }


def _ndcg(rank: int, cutoff: int) -> float:
    if rank <= 0 or rank > cutoff:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def paired_bootstrap(
    learned_ranks: Sequence[int],
    baseline_ranks: Sequence[int],
    *,
    resamples: int = 2000,
    seed: int = 20260904,
) -> dict[str, dict[str, float]]:
    if len(learned_ranks) != len(baseline_ranks) or not learned_ranks:
        raise ValueError("paired rankings must be non-empty and have equal length")
    randomizer = random.Random(seed)
    differences = {"ac_at_1": [], "mrr": []}
    count = len(learned_ranks)
    for _ in range(resamples):
        indices = [randomizer.randrange(count) for _ in range(count)]
        for metric in differences:
            learned = _metric_sample(learned_ranks, indices, metric)
            baseline = _metric_sample(baseline_ranks, indices, metric)
            differences[metric].append(learned - baseline)
    result: dict[str, dict[str, float]] = {}
    for metric, samples in differences.items():
        samples.sort()
        result[metric] = {
            "difference": _metric_sample(learned_ranks, range(count), metric)
            - _metric_sample(baseline_ranks, range(count), metric),
            "ci_low": _percentile(samples, 0.025),
            "ci_high": _percentile(samples, 0.975),
        }
    return result


def _metric_sample(ranks: Sequence[int], indices: Iterable[int], metric: str) -> float:
    values = [ranks[index] for index in indices]
    if metric == "ac_at_1":
        return sum(rank == 1 for rank in values) / len(values)
    return sum(1.0 / rank for rank in values if rank > 0) / len(values)


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(round((len(sorted_values) - 1) * fraction))
    return sorted_values[index]
