"""M8A zero-shot, stress, stability and system-holdout evaluation."""

from __future__ import annotations

import math
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import (
    build_candidate_rows,
    feature_rows,
    matrix_for_incidents,
    ranks_for_truth,
    rankings_from_scores,
    read_jsonl,
    sha256_file,
)
from .metrics import paired_bootstrap, rank_metrics
from .schema import FEATURE_COLUMNS
from .train import fit_fixed, load_model

BASELINES = ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1")
SHIFT_COLUMNS = (
    "topology_f1",
    "log1p_median_exclusive_duration_ms",
    "median_exclusive_ratio",
    "latency_z_log1p",
    "error_z_log1p",
    "in_degree",
    "out_degree",
    "ancestor_ratio",
    "descendant_ratio",
)
STABILITY_COLUMNS = (
    "log1p_median_exclusive_duration_ms",
    "latency_z_log1p",
    "topology_f1",
)


def load_dataset(directory: str | Path) -> tuple[list[dict], list[dict], dict]:
    root = Path(directory)
    return (
        read_jsonl(root / "features.jsonl"),
        read_jsonl(root / "labels.jsonl"),
        json.loads((root / "manifest.json").read_text(encoding="utf-8")),
    )


def evaluate_topology(
    directory: str | Path,
    frozen_model: xgb.Booster,
    *,
    seed: int,
) -> dict:
    features, labels, manifest = load_dataset(directory)
    labels_by_id = {label["incident_id"]: label for label in labels}
    features_by_id = {record["incident_id"]: record for record in features}
    assignments = {
        label["incident_id"]: label["experiment_kind"]
        for label in labels
        if label.get("localization_eligible")
    }
    rows = build_candidate_rows(features, labels, assignments)
    zero_faults = [
        label
        for label in labels
        if label["experiment_kind"] == "zero_shot" and label["incident_type"] == "fault"
    ]
    healthy = [
        label
        for label in labels
        if label["experiment_kind"] == "zero_shot" and label["incident_type"] == "healthy"
    ]
    localizable = [label["incident_id"] for label in zero_faults if label["localization_eligible"]]
    nontrivial = [label["incident_id"] for label in zero_faults if label["training_eligible"]]
    learned = _predict(frozen_model, rows, localizable)
    learned_ranks = ranks_for_truth(learned, labels_by_id)
    methods = {"chance": _chance(rows, nontrivial)}
    baseline_ranks = {}
    for method in BASELINES:
        ranks = {
            incident_id: _baseline_rank(features_by_id[incident_id], labels_by_id[incident_id]["root_service"], method)
            for incident_id in nontrivial
        }
        baseline_ranks[method] = ranks
        methods[method] = rank_metrics(ranks.values())
    learned_nontrivial = {incident_id: learned_ranks[incident_id] for incident_id in nontrivial}
    methods["m7_lambdamart_zero_shot"] = rank_metrics(learned_nontrivial.values())
    end_to_end = sum(learned_ranks.get(label["incident_id"], 0) == 1 for label in zero_faults) / len(zero_faults)
    paired = paired_bootstrap(
        [learned_nontrivial[value] for value in nontrivial],
        [baseline_ranks["hybrid_v1"][value] for value in nontrivial],
        seed=seed,
    )

    observed_isolation = []
    for label in zero_faults:
        snapshot = features_by_id[label["incident_id"]]["feature_snapshot"]
        observed = set(snapshot.get("observed_anomalies") or [])
        expected = set(label["expected_affected_services"])
        observed_isolation.append(
            {
                "incident_id": label["incident_id"],
                "unexpected_branch_anomalies": sorted(observed - expected),
                "missing_expected_anomalies": sorted(expected - observed),
            }
        )

    margins = _score_margins(learned, nontrivial)
    temporal = _temporal_metrics(labels, labels_by_id, rows, frozen_model)
    stability = _stability_metrics(labels, labels_by_id, rows, frozen_model)
    misses = _detection_misses(zero_faults, features_by_id)
    false_positives = _false_positives(healthy, features_by_id)
    return {
        "topology": manifest["topology"],
        "dataset_run_id": manifest["run_id"],
        "frozen_model": manifest["frozen_model"],
        "counts": {
            "zero_shot_fault_incidents": len(zero_faults),
            "healthy_controls": len(healthy),
            "detected_fault_incidents": sum(label["detected"] for label in zero_faults),
            "root_ready_fault_incidents": sum(label["root_ready"] for label in zero_faults),
            "localization_eligible": len(localizable),
            "nontrivial_eligible": len(nontrivial),
            "temporal_incidents": sum(label["experiment_kind"] == "temporal" for label in labels),
            "stability_runs": sum(label["experiment_kind"] == "stability" for label in labels),
        },
        "detection": {
            "recall": sum(label["detected"] for label in zero_faults) / len(zero_faults),
            "healthy_false_positive_rate": sum(label["detected"] for label in healthy) / len(healthy),
            "root_ready_coverage": sum(label["root_ready"] for label in zero_faults) / len(zero_faults),
        },
        "conditional_nontrivial_metrics": methods,
        "conditional_all_localizable": rank_metrics(learned_ranks.values()),
        "end_to_end_ac_at_1": end_to_end,
        "paired_vs_hybrid_95_ci": paired,
        "score_margins": margins,
        "branch_isolation": {
            "incidents_with_unexpected_branch_anomalies": sum(
                bool(value["unexpected_branch_anomalies"]) for value in observed_isolation
            ),
            "rate": sum(bool(value["unexpected_branch_anomalies"]) for value in observed_isolation)
            / len(observed_isolation),
            "examples": [value for value in observed_isolation if value["unexpected_branch_anomalies"]][:20],
        },
        "temporal_stress": temporal,
        "repeated_run_stability": stability,
        "detection_misses": {
            "counts_by_reason": dict(sorted(Counter(value["reason"] for value in misses).items())),
            "cases": misses,
        },
        "false_positives": false_positives,
        "transfer_status": _transfer_status(methods, end_to_end),
    }


def system_holdout_matrix(
    datasets: dict[str, tuple[list[dict], list[dict]]],
    frozen_model_path: str | Path,
    output_dir: str | Path,
    *,
    selected_parameters: dict,
    rounds: int,
    seed: int,
) -> dict:
    all_features = []
    all_labels = []
    system_by_id = {}
    for system, (features, labels) in datasets.items():
        all_features.extend(features)
        all_labels.extend(labels)
        system_by_id.update({label["incident_id"]: system for label in labels})
    labels_by_id = {label["incident_id"]: label for label in all_labels}
    assignments = {
        label["incident_id"]: system_by_id[label["incident_id"]]
        for label in all_labels
        if label.get("localization_eligible")
    }
    rows = build_candidate_rows(all_features, all_labels, assignments)
    frozen = load_model(frozen_model_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result = {}
    for held_out in sorted(datasets):
        train_ids = sorted(
            label["incident_id"]
            for label in all_labels
            if system_by_id[label["incident_id"]] != held_out and label.get("training_eligible")
        )
        test_ids = sorted(
            label["incident_id"]
            for label in all_labels
            if system_by_id[label["incident_id"]] == held_out and label.get("training_eligible")
        )
        cross = fit_fixed(rows, train_ids, selected_parameters, rounds=rounds, seed=seed)
        model_path = destination / f"holdout-{held_out.lower()}.json"
        cross.save_model(model_path)
        cross_ranks = ranks_for_truth(_predict(cross, rows, test_ids), labels_by_id)
        frozen_ranks = ranks_for_truth(_predict(frozen, rows, test_ids), labels_by_id)
        result[held_out] = {
            "train_systems": sorted(set(datasets) - {held_out}),
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "cross_model_metrics": rank_metrics(cross_ranks.values()),
            "frozen_m7_metrics": rank_metrics(frozen_ranks.values()),
            "model_sha256": sha256_file(model_path),
        }
    return result


def feature_distribution_shift(datasets: dict[str, tuple[list[dict], list[dict]]]) -> dict:
    distributions = {}
    for system, (features, labels) in datasets.items():
        eligible = {label["incident_id"] for label in labels if label.get("training_eligible")}
        values = defaultdict(list)
        for record in features:
            if record["incident_id"] not in eligible:
                continue
            for _, vector in feature_rows(record["feature_snapshot"]):
                for column in SHIFT_COLUMNS:
                    values[column].append(float(vector[column]))
        distributions[system] = {column: _distribution(samples) for column, samples in values.items()}
    shift = {}
    systems = sorted(distributions)
    for column in SHIFT_COLUMNS:
        pair_values = []
        for left_index, left in enumerate(systems):
            for right in systems[left_index + 1 :]:
                l = distributions[left][column]
                r = distributions[right][column]
                scale = max(1e-9, (l["iqr"] + r["iqr"]) / 2)
                pair_values.append(
                    {
                        "systems": [left, right],
                        "standardized_median_difference": abs(l["median"] - r["median"]) / scale,
                    }
                )
        shift[column] = max(pair_values, key=lambda value: value["standardized_median_difference"])
    return {
        "conditioning": "non-trivial localization-eligible candidate rows",
        "distributions": distributions,
        "largest_shifts": [
            {"feature": column, **value}
            for column, value in sorted(
                shift.items(),
                key=lambda item: -item[1]["standardized_median_difference"],
            )
        ],
    }


def _predict(model: xgb.Booster, rows: Sequence[dict], incident_ids: Sequence[str]) -> dict[str, list[dict]]:
    if not incident_ids:
        return {}
    matrix, _, groups, selected = matrix_for_incidents(rows, incident_ids)
    data = xgb.DMatrix(matrix, feature_names=list(FEATURE_COLUMNS))
    data.set_group(np.asarray(groups, dtype=np.uint32))
    return rankings_from_scores(selected, model.predict(data))


def _baseline_rank(record: dict, truth: str, method: str) -> int:
    ranking = record.get("m6_rankings", {}).get("rankings", {}).get(method, [])
    return next((int(item["rank"]) for item in ranking if item["service"] == truth), 0)


def _chance(rows: Sequence[dict], incident_ids: Sequence[str]) -> dict[str, float]:
    sizes = [sum(row["incident_id"] == incident_id for row in rows) for incident_id in incident_ids]
    if not sizes:
        return rank_metrics([])
    return {
        "ac_at_1": statistics.fmean(1 / size for size in sizes),
        "ac_at_3": statistics.fmean(min(3, size) / size for size in sizes),
        "mrr": statistics.fmean(sum(1 / rank for rank in range(1, size + 1)) / size for size in sizes),
        "ndcg_at_1": statistics.fmean(1 / size for size in sizes),
        "ndcg_at_3": statistics.fmean(
            sum(1 / math.log2(rank + 1) for rank in range(1, min(3, size) + 1)) / size for size in sizes
        ),
    }


def _score_margins(rankings: dict[str, list[dict]], incident_ids: Sequence[str], epsilon: float = 1e-6) -> dict:
    margins = []
    for incident_id in incident_ids:
        ranking = rankings.get(incident_id, [])
        if len(ranking) >= 2:
            margins.append(float(ranking[0]["ml_score"] - ranking[1]["ml_score"]))
    if not margins:
        return {"count": 0, "median": 0.0, "p10": 0.0, "fraction_equal_zero": 0.0, "fraction_below_epsilon": 0.0}
    return {
        "count": len(margins),
        "median": float(np.median(margins)),
        "p10": float(np.quantile(margins, 0.10)),
        "fraction_equal_zero": sum(value == 0 for value in margins) / len(margins),
        "fraction_below_epsilon": sum(value < epsilon for value in margins) / len(margins),
        "epsilon": epsilon,
    }


def _temporal_metrics(labels, labels_by_id, rows, model) -> dict:
    result = {}
    for profile in sorted({label["temporal_profile"] for label in labels if label["experiment_kind"] == "temporal"}):
        cases = [
            label
            for label in labels
            if label["experiment_kind"] == "temporal" and label["temporal_profile"] == profile
        ]
        ids = [label["incident_id"] for label in cases if label["localization_eligible"]]
        rankings = _predict(model, rows, ids)
        ranks = ranks_for_truth(rankings, labels_by_id)
        result[profile] = {
            "incidents": len(cases),
            "detection_recall": sum(label["detected"] for label in cases) / len(cases),
            "root_ready_coverage": sum(label["root_ready"] for label in cases) / len(cases),
            "conditional_metrics": rank_metrics(ranks.values()),
            "end_to_end_ac_at_1": sum(ranks.get(label["incident_id"], 0) == 1 for label in cases) / len(cases),
        }
    return result


def _stability_metrics(labels, labels_by_id, rows, model) -> dict:
    cases = [label for label in labels if label["experiment_kind"] == "stability"]
    ids = [label["incident_id"] for label in cases if label["localization_eligible"]]
    rankings = _predict(model, rows, ids)
    rows_by_id = defaultdict(list)
    for row in rows:
        rows_by_id[row["incident_id"]].append(row)
    grouped = defaultdict(list)
    for label in cases:
        grouped[label["fixed_scenario_id"]].append(label)
    fixed_results = []
    for fixed_id, repetitions in sorted(grouped.items()):
        top1 = []
        truth_ranks = []
        features = defaultdict(list)
        for label in repetitions:
            ranking = rankings.get(label["incident_id"], [])
            top1.append(ranking[0]["service"] if ranking else "<detection-miss>")
            truth_ranks.append(
                next((item["rank"] for item in ranking if item["service"] == label["root_service"]), 0)
            )
            root_row = next(
                (row for row in rows_by_id[label["incident_id"]] if row["service"] == label["root_service"]),
                None,
            )
            if root_row:
                for column in STABILITY_COLUMNS:
                    features[column].append(float(root_row[column]))
        fixed_results.append(
            {
                "fixed_scenario_id": fixed_id,
                "root_service": repetitions[0]["root_service"],
                "fault_type": repetitions[0]["fault_type"],
                "repetitions": len(repetitions),
                "top1_consistency_rate": max(Counter(top1).values()) / len(top1),
                "truth_rank_variance": float(np.var(truth_ranks)),
                "truth_ranks": truth_ranks,
                "feature_variability": {
                    column: {
                        "count": len(values),
                        "range": max(values) - min(values),
                        "standard_deviation": float(np.std(values)),
                    }
                    for column, values in features.items()
                },
            }
        )
    return {
        "fixed_scenarios": len(fixed_results),
        "runs": len(cases),
        "mean_top1_consistency_rate": statistics.fmean(
            value["top1_consistency_rate"] for value in fixed_results
        )
        if fixed_results
        else 0.0,
        "mean_truth_rank_variance": statistics.fmean(value["truth_rank_variance"] for value in fixed_results)
        if fixed_results
        else 0.0,
        "scenarios": fixed_results,
    }


def _detection_misses(labels: Sequence[dict], features_by_id: dict[str, dict]) -> list[dict]:
    result = []
    for label in labels:
        if label["detected"]:
            continue
        record = features_by_id[label["incident_id"]]
        operations = record.get("m5_anomalies", {}).get("operations", [])
        root_operations = [value for value in operations if value.get("service") == label["root_service"]]
        if not root_operations or max(int(value.get("current_samples", 0)) for value in root_operations) < 10:
            reason = "insufficient_data"
        elif any(
            float(value.get("latency_z", 0)) >= 3.5 or float(value.get("error_z", 0)) >= 3.0
            for value in root_operations
        ):
            reason = "propagation_not_detected"
        elif root_operations:
            reason = "below_threshold"
        else:
            reason = "other"
        result.append(
            {
                "incident_id": label["incident_id"],
                "root_service": label["root_service"],
                "fault_type": label["fault_type"],
                "fault_value": label["fault_value"],
                "reason": reason,
                "reason_state": record.get("m5_anomalies", {}).get("baseline_state", "unknown"),
                "root_operations": root_operations,
            }
        )
    return result


def _false_positives(labels: Sequence[dict], features_by_id: dict[str, dict]) -> list[dict]:
    result = []
    for label in labels:
        if not label["detected"]:
            continue
        record = features_by_id[label["incident_id"]]
        operations = record.get("m5_anomalies", {}).get("operations", [])
        result.append(
            {
                "incident_id": label["incident_id"],
                "observed_anomalies": record["feature_snapshot"].get("observed_anomalies") or [],
                "operations": [
                    {
                        "service": value.get("service"),
                        "operation": value.get("operation"),
                        "current_samples": value.get("current_samples"),
                        "baseline_samples": value.get("baseline_samples"),
                        "latency_z": value.get("latency_z"),
                        "error_z": value.get("error_z"),
                        "latency_anomalous": value.get("latency_anomalous"),
                        "error_anomalous": value.get("error_anomalous"),
                    }
                    for value in operations
                ],
            }
        )
    return result


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    p10, q1, median, q3, p90 = np.quantile(array, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "count": len(values),
        "p10": float(p10),
        "q1": float(q1),
        "median": float(median),
        "q3": float(q3),
        "p90": float(p90),
        "iqr": float(q3 - q1),
    }


def _transfer_status(methods: dict, end_to_end: float) -> str:
    learned = methods["m7_lambdamart_zero_shot"]["ac_at_1"]
    chance = methods["chance"]["ac_at_1"]
    hybrid = methods["hybrid_v1"]["ac_at_1"]
    if learned >= hybrid and learned >= chance + 0.20 and end_to_end >= 0.60:
        return "STRONG_TRANSFER"
    if learned >= chance + 0.10 and end_to_end >= 0.30:
        return "PARTIAL_TRANSFER"
    return "FAILED_TRANSFER"
