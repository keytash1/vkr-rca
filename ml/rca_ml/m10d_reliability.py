"""Truth-free incident reliability and selective-decision primitives for M10D-A.

The ranker may be trained with labels, but every value exposed to a fitted
reliability policy is derived from ranking scores, telemetry coverage, topology,
OOD bounds, or expert rankings.  Dataset/system/fault/root identity is never a
model feature.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import xgboost as xgb

from .m10c_schema import FEATURE_COLUMNS_M10C

SEED = 20260906
SEEDS = tuple(range(SEED, SEED + 5))
TARGETS = (0.90, 0.95)
FORBIDDEN_FEATURE_TOKENS = ("service", "system", "dataset", "fault", "root", "case")

FEATURE_COLUMNS = (
    "margin_top1_top2",
    "margin_top1_top3",
    "normalized_rank_gap",
    "inverse_candidate_count",
    "metric_coverage",
    "trace_coverage",
    "topology_coverage",
    "available_metric_family_ratio",
    "candidate_observability",
    "ood_metric",
    "ood_trace",
    "ood_topology",
    "ood_coverage",
    "incident_ood",
    "expert_agreement",
    "inverse_conformal_set_size",
    "ranking_concentration",
    "metrics_present",
    "traces_present",
    "topology_present",
)

# Larger values must always mean more reliable.  These directions are used by
# the bounded monotonic correctness estimator.
MONOTONIC_DIRECTIONS = (
    1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, 1, 1, 1, 1, 1, 1,
)

if any(any(token in name for token in FORBIDDEN_FEATURE_TOKENS) for name in FEATURE_COLUMNS):
    raise RuntimeError("identity leakage in M10D reliability schema")


def deterministic_split(ids: Sequence[str], namespace: str, modulus: int = 5) -> tuple[list[str], list[str]]:
    """Split opaque incident IDs without consulting labels or case semantics."""
    fit, calibration = [], []
    for incident_id in sorted(ids):
        digest = hashlib.sha256(f"{namespace}:{incident_id}".encode()).digest()
        (calibration if int.from_bytes(digest[:8], "big") % modulus == 0 else fit).append(incident_id)
    if not fit or not calibration:
        raise ValueError("deterministic reliability split produced an empty partition")
    return fit, calibration


def fit_ood_bounds(rows: list[dict], incident_ids: Sequence[str]) -> dict:
    """Fit robust, label-blind feature bounds on development incidents only."""
    wanted = set(incident_ids)
    selected = [row for row in rows if row["incident_id"] in wanted]
    if not selected:
        raise ValueError("OOD fit needs development rows")
    bounds = {}
    for name in FEATURE_COLUMNS_M10C:
        values = np.asarray([float(row[name]) for row in selected], dtype=float)
        bounds[name] = {
            "low": float(np.quantile(values, 0.01)),
            "high": float(np.quantile(values, 0.99)),
        }
    return bounds


def _feature_group(name: str) -> str:
    if name.startswith(("metric_", "workload_")):
        return "metric"
    if name.startswith("trace_"):
        return "trace"
    if name.startswith("topology_"):
        return "topology"
    return "coverage"


def group_ood(row: dict, bounds: dict) -> dict[str, float]:
    totals = {name: 0 for name in ("metric", "trace", "topology", "coverage")}
    outside = dict(totals)
    for name, limits in bounds.items():
        group = _feature_group(name)
        totals[group] += 1
        value = float(row[name])
        outside[group] += int(value < limits["low"] or value > limits["high"])
    return {group: outside[group] / totals[group] if totals[group] else 0.0 for group in totals}


def _softmax_concentration(scores: Sequence[float]) -> float:
    values = np.asarray(scores, dtype=float)
    values -= np.max(values)
    probabilities = np.exp(values)
    probabilities /= probabilities.sum()
    if len(probabilities) == 1:
        return 1.0
    entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12))))
    return 1.0 - entropy / math.log(len(probabilities))


def _rank_for(ranking: list[dict], service: str) -> int:
    return next(int(item["rank"]) for item in ranking if item["service"] == service)


def build_incident_record(
    incident_id: str,
    ranking: list[dict],
    source_rows: dict[tuple[str, str], dict],
    ood_bounds: dict,
    conformal_quantile: float,
    metric_ranking: list[dict] | None = None,
    trace_ranking: list[dict] | None = None,
    include_target: bool = True,
) -> dict:
    """Build one incident row; identity is retained only as an opaque routing key."""
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    first = ordered[0]
    second = ordered[min(1, len(ordered) - 1)]
    third = ordered[min(2, len(ordered) - 1)]
    scores = [float(item["score"]) for item in ordered]
    score_range = max(max(scores) - min(scores), 1e-9)
    top_row = source_rows[(incident_id, first["service"])]
    ood = group_ood(top_row, ood_bounds)
    candidate_count = len(ordered)
    metric_rank = _rank_for(metric_ranking, first["service"]) if metric_ranking else 1
    trace_rank = _rank_for(trace_ranking, first["service"]) if trace_ranking else 1
    disagreement = abs(metric_rank - trace_rank) / max(candidate_count - 1, 1)
    set_size = min(candidate_count, max(1, math.ceil(conformal_quantile * candidate_count)))
    metric_coverage = float(top_row["coverage_metric_family_ratio"])
    trace_coverage = float(top_row["coverage_trace_fraction"])
    topology_coverage = float(top_row["coverage_has_topology"])
    observability = (
        float(top_row["coverage_has_metrics"])
        + float(top_row["coverage_has_traces"])
        + topology_coverage
    ) / 3.0
    features = {
        "margin_top1_top2": (scores[0] - float(second["score"])) / score_range,
        "margin_top1_top3": (scores[0] - float(third["score"])) / score_range,
        "normalized_rank_gap": (scores[0] - float(second["score"])) / max(abs(scores[0]), abs(float(second["score"])), 1e-9),
        "inverse_candidate_count": 1.0 / candidate_count,
        "metric_coverage": metric_coverage,
        "trace_coverage": trace_coverage,
        "topology_coverage": topology_coverage,
        "available_metric_family_ratio": float(top_row.get("metric_available_family_ratio", metric_coverage)),
        "candidate_observability": observability,
        "ood_metric": ood["metric"],
        "ood_trace": ood["trace"],
        "ood_topology": ood["topology"],
        "ood_coverage": ood["coverage"],
        "incident_ood": float(np.mean(list(ood.values()))),
        "expert_agreement": 1.0 - disagreement,
        "inverse_conformal_set_size": 1.0 / set_size,
        "ranking_concentration": _softmax_concentration(scores),
        "metrics_present": float(top_row["coverage_has_metrics"]),
        "traces_present": float(top_row["coverage_has_traces"]),
        "topology_present": topology_coverage,
    }
    result = {
        "incident_id": incident_id,
        "top1_service": first["service"],
        "candidate_count": candidate_count,
        "conformal_set_size_90": set_size,
        "conformal_candidates_90": [item["service"] for item in ordered[:set_size]],
        "features": features,
    }
    if include_target:
        result["top1_correct"] = int(first["label"]) == 1
        result["truth_rank"] = next(int(item["rank"]) for item in ordered if int(item["label"]) == 1)
    return result


def feature_matrix(records: Sequence[dict]) -> np.ndarray:
    return np.asarray([[float(record["features"][name]) for name in FEATURE_COLUMNS] for record in records], dtype=float)


def targets(records: Sequence[dict]) -> np.ndarray:
    return np.asarray([int(record["top1_correct"]) for record in records], dtype=float)


@dataclass
class IsotonicModel:
    upper: list[float]
    values: list[float]

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        x = matrix[:, 0]
        return np.asarray([self.values[min(int(np.searchsorted(self.upper, value, side="left")), len(self.values) - 1)] for value in x])


def fit_isotonic(records: Sequence[dict]) -> IsotonicModel:
    pairs = sorted((float(record["features"]["margin_top1_top2"]), int(record["top1_correct"])) for record in records)
    blocks: list[dict] = []
    for x_value, target in pairs:
        blocks.append({"low": x_value, "high": x_value, "sum": float(target), "n": 1})
        while len(blocks) >= 2 and blocks[-2]["sum"] / blocks[-2]["n"] > blocks[-1]["sum"] / blocks[-1]["n"]:
            right = blocks.pop(); left = blocks.pop()
            blocks.append({"low": left["low"], "high": right["high"], "sum": left["sum"] + right["sum"], "n": left["n"] + right["n"]})
    return IsotonicModel([float(block["high"]) for block in blocks], [block["sum"] / block["n"] for block in blocks])


@dataclass
class LogisticModel:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        normalized = (matrix - self.mean) / self.scale
        logits = np.clip(normalized @ self.weights + self.bias, -30, 30)
        return 1.0 / (1.0 + np.exp(-logits))


def fit_logistic(records: Sequence[dict], l2: float = 1.0, iterations: int = 1200) -> LogisticModel:
    matrix = feature_matrix(records); target = targets(records)
    mean = matrix.mean(axis=0); scale = matrix.std(axis=0)
    scale[scale < 1e-9] = 1.0
    normalized = (matrix - mean) / scale
    weights = np.zeros(matrix.shape[1]); bias = math.log((target.mean() + 1e-3) / (1 - target.mean() + 1e-3))
    for step in range(iterations):
        logits = np.clip(normalized @ weights + bias, -30, 30)
        prediction = 1.0 / (1.0 + np.exp(-logits))
        rate = 0.08 / math.sqrt(1 + step / 100)
        weights -= rate * ((normalized.T @ (prediction - target)) / len(target) + l2 * weights / len(target))
        bias -= rate * float(np.mean(prediction - target))
    return LogisticModel(mean, scale, weights, bias)


@dataclass
class BoostingModel:
    booster: xgb.Booster

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        return self.booster.predict(xgb.DMatrix(matrix, feature_names=list(FEATURE_COLUMNS)))


def fit_monotonic_boosting(records: Sequence[dict], seed: int) -> BoostingModel:
    matrix = feature_matrix(records); target = targets(records)
    data = xgb.DMatrix(matrix, label=target, feature_names=list(FEATURE_COLUMNS))
    params = {
        "objective": "binary:logistic", "eval_metric": "logloss", "tree_method": "hist",
        "max_depth": 2, "eta": 0.05, "min_child_weight": 8, "subsample": 0.8,
        "colsample_bytree": 0.8, "nthread": 4, "seed": seed,
        "monotone_constraints": "(" + ",".join(map(str, MONOTONIC_DIRECTIONS)) + ")",
    }
    return BoostingModel(xgb.train(params, data, num_boost_round=32, verbose_eval=False))


def predict_method(method: str, fitted: object | None, records: Sequence[dict]) -> np.ndarray:
    matrix = feature_matrix(records)
    if method == "margin":
        return matrix[:, FEATURE_COLUMNS.index("margin_top1_top2")]
    if fitted is None:
        raise ValueError(f"{method} requires a fitted model")
    return fitted.predict(matrix)


def fit_method(method: str, records: Sequence[dict], seed: int = SEED) -> object | None:
    if method == "margin":
        return None
    if method == "isotonic":
        return fit_isotonic(records)
    if method in {"logistic", "risk_control", "mondrian"}:
        return fit_logistic(records)
    if method == "monotonic_boosting":
        return fit_monotonic_boosting(records, seed)
    raise ValueError(method)


def empirical_threshold(scores: Sequence[float], labels: Sequence[int], target_accuracy: float) -> dict:
    candidates = sorted(set(float(value) for value in scores))
    feasible = []
    for threshold in candidates:
        selected = [index for index, score in enumerate(scores) if float(score) >= threshold]
        accuracy = sum(int(labels[index]) for index in selected) / len(selected)
        if accuracy >= target_accuracy:
            feasible.append((len(selected), -threshold, threshold, accuracy))
    if not feasible:
        return {"threshold": None, "calibration_coverage": 0.0, "calibration_accuracy": None}
    count, _, threshold, accuracy = max(feasible)
    return {"threshold": float(threshold), "calibration_coverage": count / len(scores), "calibration_accuracy": accuracy}


def _wilson_lower(successes: int, count: int, z: float = 1.6448536269514722) -> float:
    if count == 0:
        return 0.0
    rate = successes / count
    denominator = 1 + z * z / count
    centre = rate + z * z / (2 * count)
    spread = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
    return (centre - spread) / denominator


def risk_control_threshold(scores: Sequence[float], labels: Sequence[int], target_accuracy: float) -> dict:
    candidates = sorted(set(float(value) for value in scores))
    feasible = []
    for threshold in candidates:
        selected = [index for index, score in enumerate(scores) if float(score) >= threshold]
        successes = sum(int(labels[index]) for index in selected)
        lower = _wilson_lower(successes, len(selected))
        if lower >= target_accuracy:
            feasible.append((len(selected), -threshold, threshold, successes / len(selected), lower))
    if not feasible:
        return {"threshold": None, "calibration_coverage": 0.0, "calibration_accuracy": None, "wilson_lower": None}
    count, _, threshold, accuracy, lower = max(feasible)
    return {"threshold": float(threshold), "calibration_coverage": count / len(scores), "calibration_accuracy": accuracy, "wilson_lower": lower}


def fit_regime_boundaries(records: Sequence[dict]) -> dict:
    coverage = [record["features"]["candidate_observability"] for record in records]
    ood = [record["features"]["incident_ood"] for record in records]
    candidates = [record["candidate_count"] for record in records]
    return {
        "coverage_median": float(np.median(coverage)),
        "ood_q75": float(np.quantile(ood, 0.75)),
        "candidate_count_median": float(np.median(candidates)),
    }


def regime(record: dict, boundaries: dict) -> str:
    feature = record["features"]
    missing = min(feature["metrics_present"], feature["traces_present"], feature["topology_present"]) < 1
    return "|".join((
        "coverage_low" if feature["candidate_observability"] < boundaries["coverage_median"] else "coverage_high",
        "ood_high" if feature["incident_ood"] > boundaries["ood_q75"] else "ood_normal",
        "candidates_small" if record["candidate_count"] <= boundaries["candidate_count_median"] else "candidates_large",
        "missing" if missing else "complete",
    ))


def fit_policy(method: str, fitted: object | None, calibration: Sequence[dict], target_accuracy: float,
               regime_training: Sequence[dict] | None = None) -> dict:
    scores = predict_method(method, fitted, calibration)
    labels = [int(record["top1_correct"]) for record in calibration]
    if method == "risk_control":
        result = risk_control_threshold(scores, labels, target_accuracy)
    else:
        result = empirical_threshold(scores, labels, target_accuracy)
    result.update({"method": method, "target_accuracy": target_accuracy})
    if method == "mondrian":
        boundaries = fit_regime_boundaries(regime_training or calibration)
        thresholds = {}
        groups = sorted(set(regime(record, boundaries) for record in calibration))
        for group in groups:
            selected = [index for index, record in enumerate(calibration) if regime(record, boundaries) == group]
            if len(selected) >= 20:
                local = empirical_threshold([scores[index] for index in selected], [labels[index] for index in selected], target_accuracy)
                thresholds[group] = local["threshold"]
        result["regime_boundaries"] = boundaries
        result["regime_thresholds"] = thresholds
        result["minimum_group_size"] = 20
    return result


def policy_accepts(policy: dict, record: dict, score: float) -> bool:
    threshold = policy["threshold"]
    if policy["method"] == "mondrian":
        group = regime(record, policy["regime_boundaries"])
        threshold = policy["regime_thresholds"].get(group, threshold)
    if threshold is None:
        return False
    return float(score) >= float(threshold)


def evaluate_policy(records: Sequence[dict], scores: Sequence[float], policy: dict) -> dict:
    accepted = [index for index, (record, score) in enumerate(zip(records, scores, strict=True)) if policy_accepts(policy, record, score)]
    accuracy = float(np.mean([records[index]["top1_correct"] for index in accepted])) if accepted else None
    mrr = float(np.mean([1 / records[index]["truth_rank"] for index in accepted])) if accepted else None
    curve = risk_coverage(records, scores)
    return {
        "cases": len(records), "accepted": len(accepted), "coverage": len(accepted) / len(records) if records else 0.0,
        "selective_ac_at_1": accuracy, "selective_mrr": mrr,
        "risk": None if accuracy is None else 1 - accuracy,
        "aurc": curve["aurc"], "risk_coverage_curve": curve["curve"],
    }


def risk_coverage(records: Sequence[dict], scores: Sequence[float]) -> dict:
    order = sorted(range(len(records)), key=lambda index: (-float(scores[index]), records[index]["incident_id"]))
    curve, risks = [], []
    mistakes = 0
    for position, index in enumerate(order, 1):
        mistakes += not bool(records[index]["top1_correct"])
        risk = mistakes / position
        risks.append(risk)
        curve.append({"coverage": position / len(order), "risk": risk})
    aurc = float(np.trapezoid(risks, dx=1 / len(risks))) if risks else None
    return {"aurc": aurc, "curve": curve}


def calibration_metrics(records: Sequence[dict], probabilities: Sequence[float], bins: int = 10) -> dict:
    labels = np.asarray([int(record["top1_correct"]) for record in records], dtype=float)
    values = np.clip(np.asarray(probabilities, dtype=float), 0, 1)
    brier = float(np.mean((values - labels) ** 2))
    diagram = []
    ece = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        mask = (values >= low) & ((values <= high) if index == bins - 1 else (values < high))
        if not mask.any():
            continue
        predicted = float(values[mask].mean()); observed = float(labels[mask].mean()); count = int(mask.sum())
        ece += count / len(values) * abs(predicted - observed)
        diagram.append({"low": low, "high": high, "count": count, "mean_score": predicted, "observed_accuracy": observed})
    return {"brier": brier, "ece": ece, "reliability_diagram": diagram}


def bootstrap_accuracy_delta(records: Sequence[dict], scores: Sequence[float], baseline_scores: Sequence[float],
                             coverage: float, resamples: int = 10_000, seed: int = SEED) -> dict:
    """Compare score ordering with margin ordering at identical accepted coverage."""
    count = max(1, min(len(records), round(coverage * len(records))))
    selected = set(sorted(range(len(records)), key=lambda i: (-float(scores[i]), records[i]["incident_id"]))[:count])
    baseline = set(sorted(range(len(records)), key=lambda i: (-float(baseline_scores[i]), records[i]["incident_id"]))[:count])
    contributions = [
        (int(i in selected) * int(records[i]["top1_correct"]) - int(i in baseline) * int(records[i]["top1_correct"])) / count
        for i in range(len(records))
    ]
    rng = np.random.default_rng(seed)
    samples = np.empty(resamples)
    for index in range(resamples):
        draw = rng.integers(0, len(records), len(records))
        samples[index] = float(np.sum(np.asarray(contributions)[draw]))
    return {"difference": float(np.sum(contributions)), "ci_low": float(np.quantile(samples, 0.025)),
            "ci_high": float(np.quantile(samples, 0.975)), "matched_coverage": count / len(records),
            "resamples": resamples, "seed": seed}


def serializable_model(method: str, fitted: object | None) -> dict:
    if fitted is None:
        return {"kind": "margin", "feature": "margin_top1_top2"}
    if isinstance(fitted, IsotonicModel):
        return {"kind": "isotonic", "upper": fitted.upper, "values": fitted.values}
    if isinstance(fitted, LogisticModel):
        return {"kind": "logistic", "mean": fitted.mean.tolist(), "scale": fitted.scale.tolist(),
                "weights": fitted.weights.tolist(), "bias": fitted.bias}
    if isinstance(fitted, BoostingModel):
        return {"kind": "xgboost", "note": "booster stored separately"}
    raise TypeError(type(fitted))


def ensure_truth_free_inference(record: dict) -> dict:
    """Return the deployable view and intentionally remove evaluation targets."""
    return {key: value for key, value in record.items() if key not in {"top1_correct", "truth_rank"}}
