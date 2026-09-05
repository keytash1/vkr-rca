"""Truth-free active diagnostic planning primitives for M10D-C."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from .m10c_schema import FEATURE_COLUMNS_M10C

ACTION_NAMES = (
    "GET_LATENCY_METRICS", "GET_ERROR_METRICS", "GET_CPU_METRICS",
    "GET_MEMORY_METRICS", "GET_NETWORK_METRICS", "GET_DISK_METRICS",
    "GET_WORKLOAD_METRICS", "GET_TRACE_EVIDENCE", "GET_TOPOLOGY",
    "GET_DEPENDENCY_EVIDENCE",
)
METRIC_ACTIONS = ACTION_NAMES[:7]
BASE_COSTS = {name: 1 for name in METRIC_ACTIONS}
BASE_COSTS.update({"GET_TRACE_EVIDENCE": 2, "GET_TOPOLOGY": 1,
                   "GET_DEPENDENCY_EVIDENCE": 2})
UNIFORM_COSTS = {name: 1 for name in ACTION_NAMES}
TRACE_EXPENSIVE_COSTS = {**BASE_COSTS, "GET_TRACE_EVIDENCE": 3,
                         "GET_DEPENDENCY_EVIDENCE": 3}
COST_SCHEMES = {"base": BASE_COSTS, "uniform": UNIFORM_COSTS,
                "trace_expensive": TRACE_EXPENSIVE_COSTS}

ACTION_PREFIXES = {
    "GET_LATENCY_METRICS": ("metric_latency_",),
    "GET_ERROR_METRICS": ("metric_error_rate_",),
    "GET_CPU_METRICS": ("metric_cpu_",),
    "GET_MEMORY_METRICS": ("metric_memory_",),
    "GET_NETWORK_METRICS": ("metric_network_",),
    "GET_DISK_METRICS": ("metric_disk_",),
    "GET_WORKLOAD_METRICS": ("metric_traffic_rate_", "workload_"),
    "GET_TRACE_EVIDENCE": ("trace_",),
    "GET_TOPOLOGY": ("topology_",),
    "GET_DEPENDENCY_EVIDENCE": (
        "metric_dependency_", "metric_saturation_", "metric_runtime_",
        "metric_database_", "metric_cache_", "metric_queue_",
    ),
}

STATE_FIELDS = (
    "spent_cost", "candidate_count", "available_fraction", "revealed_fraction",
    "top1_top2_margin", "top1_top3_margin", "ranking_concentration",
    "prediction_set_size", "metric_coverage", "trace_coverage",
    "topology_coverage", "ood_score", "expert_disagreement", "verifier_support",
)
POLICY_FEATURES = (
    STATE_FIELDS
    + tuple(f"revealed_{name.lower()}" for name in ACTION_NAMES)
    + tuple(f"action_{name.lower()}" for name in ACTION_NAMES)
    + ("action_cost", "action_is_metric", "action_is_trace_like")
)


@dataclass(frozen=True)
class VisibleState:
    """Serializable policy input. It intentionally cannot carry hidden evidence."""

    incident_id: str
    available_actions: tuple[str, ...]
    revealed_actions: tuple[str, ...]
    spent_cost: float
    candidate_count: int
    top_services: tuple[str, ...]
    top_scores: tuple[float, ...]
    top1_top2_margin: float
    top1_top3_margin: float
    ranking_concentration: float
    prediction_set_size: int
    metric_coverage: float
    trace_coverage: float
    topology_coverage: float
    ood_score: float = 0.0
    expert_disagreement: float = 0.0
    verifier_support: float = 0.0

    def public_dict(self) -> dict:
        value = asdict(self)
        forbidden = {"label", "root", "truth", "full_rows", "hidden"}
        if forbidden & set(value):
            raise AssertionError("hidden evidence leaked into visible state")
        return value


def source_action_availability(record: Mapping) -> tuple[str, ...]:
    families = set(record["features"].get("source_families", ()))
    candidates = record["features"].get("candidates", ())
    has_trace = any(bool(item.get("has_traces")) for item in candidates)
    has_topology = any(bool(item.get("has_topology")) for item in candidates)
    mapping = {
        "GET_LATENCY_METRICS": "latency",
        "GET_ERROR_METRICS": "error_rate",
        "GET_CPU_METRICS": "cpu",
        "GET_MEMORY_METRICS": "memory",
        "GET_NETWORK_METRICS": "network",
        "GET_DISK_METRICS": "disk",
        "GET_WORKLOAD_METRICS": "traffic_rate",
    }
    result = [action for action, family in mapping.items() if family in families]
    if has_trace:
        result.extend(("GET_TRACE_EVIDENCE", "GET_DEPENDENCY_EVIDENCE"))
    elif "dependency" in families:
        result.append("GET_DEPENDENCY_EVIDENCE")
    if has_topology:
        result.append("GET_TOPOLOGY")
    return tuple(action for action in ACTION_NAMES if action in result)


def _column_visible(column: str, revealed: set[str]) -> bool:
    if column in {"coverage_has_metrics", "coverage_metric_family_ratio",
                  "coverage_candidate_metric_ratio", "metric_available_family_count",
                  "metric_available_family_ratio", "metric_max_shift_score",
                  "metric_top2_score"}:
        return bool(revealed & set(METRIC_ACTIONS))
    if column in {"coverage_has_traces", "coverage_trace_fraction",
                  "coverage_candidate_trace_ratio"}:
        return "GET_TRACE_EVIDENCE" in revealed
    if column == "coverage_has_topology":
        return "GET_TOPOLOGY" in revealed
    if column == "topology_active_trace_coverage":
        return {"GET_TRACE_EVIDENCE", "GET_TOPOLOGY"} <= revealed
    return any(action in revealed and column.startswith(prefixes)
               for action, prefixes in ACTION_PREFIXES.items())


def mask_rows(rows: Sequence[dict], revealed_actions: Iterable[str],
              columns: Sequence[str]) -> list[dict]:
    revealed = set(revealed_actions)
    unknown = revealed - set(ACTION_NAMES)
    if unknown:
        raise ValueError(f"unknown diagnostic actions: {sorted(unknown)}")
    result = []
    for source in rows:
        row = dict(source)
        for column in columns:
            if not _column_visible(column, revealed):
                row[column] = 0.0
        result.append(row)
    return result


def full_evidence_columns_covered(columns: Sequence[str]) -> bool:
    return all(_column_visible(column, set(ACTION_NAMES)) for column in columns)


def visible_feature_mask(revealed_actions: Iterable[str],
                         columns: Sequence[str]) -> np.ndarray:
    """Return the ordered numeric mask used by vectorized simulation."""
    revealed = set(revealed_actions)
    return np.asarray([float(_column_visible(column, revealed)) for column in columns],
                      dtype=np.float32)


def normalized_gap(first: float, other: float) -> float:
    return (first - other) / max(abs(first), abs(other), 1e-9)


def score_gap_nonconformity(ranking: Sequence[dict]) -> float:
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    first = float(ordered[0]["score"])
    truth = next(item for item in ordered if int(item["label"]) == 1)
    return max(0.0, normalized_gap(first, float(truth["score"])))


def gap_quantile(rankings: Mapping[str, Sequence[dict]], coverage: float = .9) -> float:
    if not rankings or not 0 < coverage < 1:
        raise ValueError("non-empty rankings and a proper coverage are required")
    values = sorted(score_gap_nonconformity(value) for value in rankings.values())
    index = min(len(values) - 1, math.ceil((len(values) + 1) * coverage) - 1)
    return float(values[index])


def gap_prediction_set(ranking: Sequence[dict], quantile: float) -> tuple[str, ...]:
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    first = float(ordered[0]["score"])
    selected = [item["service"] for item in ordered
                if normalized_gap(first, float(item["score"])) <= quantile + 1e-12]
    return tuple(selected or [ordered[0]["service"]])


def build_visible_state(incident_id: str, ranking: Sequence[dict],
                        available_actions: Sequence[str], revealed_actions: Sequence[str],
                        spent_cost: float, prediction_quantile: float) -> VisibleState:
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    scores = [float(item["score"]) for item in ordered]
    first = scores[0]
    second = scores[1] if len(scores) > 1 else first
    third = scores[2] if len(scores) > 2 else second
    revealed = set(revealed_actions)
    metric_available = set(available_actions) & set(METRIC_ACTIONS)
    metric_revealed = revealed & set(METRIC_ACTIONS)
    return VisibleState(
        incident_id=incident_id,
        available_actions=tuple(available_actions),
        revealed_actions=tuple(action for action in ACTION_NAMES if action in revealed),
        spent_cost=float(spent_cost),
        candidate_count=len(ordered),
        top_services=tuple(item["service"] for item in ordered[:3]),
        top_scores=tuple(scores[:3]),
        top1_top2_margin=normalized_gap(first, second),
        top1_top3_margin=normalized_gap(first, third),
        ranking_concentration=float(np.std(scores)),
        prediction_set_size=len(gap_prediction_set(ordered, prediction_quantile)),
        metric_coverage=len(metric_revealed) / max(1, len(metric_available)),
        trace_coverage=float("GET_TRACE_EVIDENCE" in revealed),
        topology_coverage=float("GET_TOPOLOGY" in revealed),
    )


def policy_vector(state: VisibleState, action: str,
                  costs: Mapping[str, int] = BASE_COSTS) -> np.ndarray:
    if action not in ACTION_NAMES or action not in state.available_actions:
        raise ValueError("policy can score only available canonical actions")
    revealed = set(state.revealed_actions)
    state_values = (
        state.spent_cost, state.candidate_count,
        len(state.available_actions) / len(ACTION_NAMES),
        len(revealed) / max(1, len(state.available_actions)),
        state.top1_top2_margin, state.top1_top3_margin,
        state.ranking_concentration, state.prediction_set_size,
        state.metric_coverage, state.trace_coverage, state.topology_coverage,
        state.ood_score, state.expert_disagreement, state.verifier_support,
    )
    mask = tuple(float(name in revealed) for name in ACTION_NAMES)
    one_hot = tuple(float(name == action) for name in ACTION_NAMES)
    descriptor = (float(costs[action]), float(action in METRIC_ACTIONS),
                  float(action in {"GET_TRACE_EVIDENCE", "GET_DEPENDENCY_EVIDENCE"}))
    vector = np.asarray(state_values + mask + one_hot + descriptor, dtype=np.float32)
    if len(vector) != len(POLICY_FEATURES):
        raise AssertionError("planner feature schema mismatch")
    return vector


def transition(state: VisibleState, action: str, costs: Mapping[str, int], budget: float) -> tuple[tuple[str, ...], float]:
    if action not in state.available_actions or action in state.revealed_actions:
        raise ValueError("action is unavailable or already revealed")
    next_cost = state.spent_cost + costs[action]
    if next_cost > budget + 1e-12:
        raise ValueError("action exceeds diagnostic budget")
    revealed = tuple(name for name in ACTION_NAMES
                     if name in set(state.revealed_actions) | {action})
    return revealed, float(next_cost)


def realized_utility(before: Sequence[dict], after: Sequence[dict],
                     set_before: int, set_after: int, action_cost: float,
                     *, alpha: float = .20, cost_weight: float = .02) -> float:
    rank_before = next(int(item["rank"]) for item in before if int(item["label"]) == 1)
    rank_after = next(int(item["rank"]) for item in after if int(item["label"]) == 1)
    count = max(1, len(before))
    return ((1.0 / rank_after - 1.0 / rank_before)
            + alpha * (set_before - set_after) / count
            - cost_weight * action_cost)


def deterministic_random_action(incident_id: str, revealed: Sequence[str],
                                actions: Sequence[str], seed: int) -> str:
    return min(actions, key=lambda action: hashlib.sha256(
        f"{seed}:{incident_id}:{','.join(sorted(revealed))}:{action}".encode()).hexdigest())


def choose_expected_utility(state: VisibleState, actions: Sequence[str],
                            predict: Callable[[np.ndarray], float | np.ndarray],
                            costs: Mapping[str, int] = BASE_COSTS) -> tuple[str | None, float]:
    if not actions:
        return None, float("-inf")
    matrix = np.stack([policy_vector(state, action, costs) for action in actions])
    predicted = np.asarray(predict(matrix), dtype=float).reshape(-1)
    if len(predicted) == 1 and len(actions) == 1:
        predicted = np.repeat(predicted, 1)
    if len(predicted) != len(actions):
        raise ValueError("planner predictor must return one utility per action")
    scored = list(zip(predicted.tolist(), actions, strict=True))
    score, action = max(scored, key=lambda item: (item[0], tuple(-ord(c) for c in item[1])))
    return action, score
