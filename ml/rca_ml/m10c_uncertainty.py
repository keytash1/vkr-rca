"""Split-conformal rank sets and isolated selective prediction for M10C."""

from __future__ import annotations

import math

import numpy as np


def assert_disjoint_partitions(fit_ids: list[str], calibration_ids: list[str], test_ids: list[str]) -> None:
    fit, calibration, test = set(fit_ids), set(calibration_ids), set(test_ids)
    if fit & calibration or fit & test or calibration & test:
        raise ValueError("fit, calibration and test partitions must be disjoint")
    if not fit or not calibration or not test:
        raise ValueError("fit, calibration and test partitions must be non-empty")


def normalized_truth_rank(ranking: list[dict]) -> float:
    truth = next(int(item["rank"]) for item in ranking if int(item["label"]) == 1)
    return truth / len(ranking)


def conformal_quantile(calibration_rankings: dict[str, list[dict]], coverage: float) -> float:
    if not 0 < coverage < 1 or not calibration_rankings:
        raise ValueError("coverage and non-empty calibration rankings are required")
    scores = sorted(normalized_truth_rank(value) for value in calibration_rankings.values())
    index = min(len(scores) - 1, math.ceil((len(scores) + 1) * coverage) - 1)
    return float(scores[index])


def prediction_set(ranking: list[dict], quantile: float) -> list[str]:
    size = min(len(ranking), max(1, math.ceil(quantile * len(ranking))))
    return [item["service"] for item in sorted(ranking, key=lambda x: int(x["rank"]))[:size]]


def evaluate_conformal(calibration: dict[str, list[dict]], test: dict[str, list[dict]], coverage: float) -> dict:
    quantile = conformal_quantile(calibration, coverage)
    sizes, covered = [], []
    for ranking in test.values():
        selected = prediction_set(ranking, quantile)
        truth = next(item["service"] for item in ranking if int(item["label"]) == 1)
        sizes.append(len(selected)); covered.append(truth in selected)
    return {
        "nominal_coverage": coverage, "calibration_cases": len(calibration), "test_cases": len(test),
        "quantile": quantile, "empirical_coverage": float(np.mean(covered)),
        "mean_set_size": float(np.mean(sizes)), "median_set_size": float(np.median(sizes)),
        "p90_set_size": float(np.quantile(sizes, .9)),
    }


def reliability_record(ranking: list[dict], source_rows: dict[tuple[str, str], dict],
                       incident: str, ood_score: float = 0.0, expert_disagreement: float = 0.0) -> dict:
    ordered = sorted(ranking, key=lambda item: int(item["rank"]))
    first, second = ordered[0], ordered[1] if len(ordered) > 1 else {"score": first["score"]}
    scale = max(abs(float(first["score"])), abs(float(second["score"])), 1e-9)
    row = source_rows[(incident, first["service"])]
    margin = (float(first["score"]) - float(second["score"])) / scale
    coverage = (float(row["coverage_has_metrics"]) + float(row["coverage_has_traces"])
                + float(row["coverage_has_topology"])) / 3
    quality = margin - .25 * expert_disagreement + .1 * coverage - .05 * ood_score
    return {"incident_id": incident, "quality": quality, "correct": int(first["label"]) == 1,
            "truth_rank": next(int(item["rank"]) for item in ordered if int(item["label"]) == 1)}


def calibrate_abstention(records: list[dict], target_accuracy: float) -> dict:
    if not records:
        raise ValueError("calibration records are empty")
    candidates = sorted({float(item["quality"]) for item in records})
    feasible = []
    for threshold in candidates:
        accepted = [item for item in records if float(item["quality"]) >= threshold]
        accuracy = sum(item["correct"] for item in accepted) / len(accepted)
        if accuracy >= target_accuracy:
            feasible.append((len(accepted), -threshold, threshold, accuracy))
    if not feasible:
        return {"threshold": float("inf"), "calibration_coverage": 0.0,
                "calibration_accuracy": None, "target_accuracy": target_accuracy}
    _, _, threshold, accuracy = max(feasible)
    accepted = [item for item in records if float(item["quality"]) >= threshold]
    return {"threshold": threshold, "calibration_coverage": len(accepted) / len(records),
            "calibration_accuracy": accuracy, "target_accuracy": target_accuracy}


def evaluate_abstention(records: list[dict], threshold: float) -> dict:
    ordered = sorted(records, key=lambda item: -float(item["quality"]))
    accepted = [item for item in ordered if float(item["quality"]) >= threshold]
    coverage = len(accepted) / len(records) if records else 0.0
    accuracy = sum(item["correct"] for item in accepted) / len(accepted) if accepted else None
    mrr = sum(1 / item["truth_rank"] for item in accepted) / len(accepted) if accepted else None
    curve, risks = [], []
    mistakes = 0
    for index, item in enumerate(ordered, 1):
        mistakes += not item["correct"]
        risk = mistakes / index
        risks.append(risk)
        curve.append({"coverage": index / len(ordered), "risk": risk})
    aurc = float(np.trapezoid(risks, dx=1 / len(risks))) if risks else None
    return {"cases": len(records), "accepted": len(accepted), "coverage": coverage,
            "selective_ac_at_1": accuracy, "selective_mrr": mrr,
            "risk": 1 - accuracy if accuracy is not None else None,
            "aurc": aurc, "risk_coverage_curve": curve}
