"""Honest test, end-to-end, holdout, permutation and explainability evaluation."""

from __future__ import annotations

import math
from collections.abc import Sequence

import xgboost as xgb

from .dataset import matrix_for_incidents, ranks_for_truth
from .metrics import paired_bootstrap, rank_metrics
from .schema import FEATURE_COLUMNS
from .train import dmatrix, fit_fixed, predict_rows

BASELINES = ("max_severity", "topology_consistency", "local_evidence", "hybrid_v1")


def evaluate_experiment(
    feature_records: Sequence[dict],
    labels: Sequence[dict],
    rows: Sequence[dict],
    assignments: dict[str, str],
    model: xgb.Booster,
    *,
    selected_parameters: dict,
    rounds: int,
    seed: int,
) -> dict:
    labels_by_id = {label["incident_id"]: label for label in labels}
    features_by_id = {record["incident_id"]: record for record in feature_records}
    fault_labels = [label for label in labels if label["incident_type"] == "fault"]
    healthy_labels = [label for label in labels if label["incident_type"] == "healthy"]
    test_all_ids = sorted(
        incident_id
        for incident_id, split in assignments.items()
        if split == "test" and labels_by_id[incident_id]["localization_eligible"]
    )
    test_nontrivial_ids = [
        incident_id for incident_id in test_all_ids if labels_by_id[incident_id]["training_eligible"]
    ]
    learned_test = predict_rows(model, rows, test_all_ids)
    learned_test_ranks = ranks_for_truth(learned_test, labels_by_id)
    test_metrics = {}
    baseline_rank_maps = {}
    for baseline in BASELINES:
        ranks = {
            incident_id: _baseline_rank(features_by_id[incident_id], labels_by_id[incident_id]["root_service"], baseline)
            for incident_id in test_nontrivial_ids
        }
        baseline_rank_maps[baseline] = ranks
        test_metrics[baseline] = rank_metrics(ranks.values())
    nontrivial_learned_ranks = {incident_id: learned_test_ranks[incident_id] for incident_id in test_nontrivial_ids}
    test_metrics["m7_lambdamart"] = rank_metrics(nontrivial_learned_ranks.values())
    test_metrics["chance"] = _chance_metrics(rows, test_nontrivial_ids)

    all_localizable_ids = sorted(label["incident_id"] for label in fault_labels if label["localization_eligible"])
    learned_all = predict_rows(model, rows, all_localizable_ids)
    learned_all_ranks = ranks_for_truth(learned_all, labels_by_id)
    end_to_end_successes = sum(learned_all_ranks.get(label["incident_id"], 0) == 1 for label in fault_labels)

    paired = {
        baseline: paired_bootstrap(
            [nontrivial_learned_ranks[incident_id] for incident_id in test_nontrivial_ids],
            [baseline_rank_maps[baseline][incident_id] for incident_id in test_nontrivial_ids],
            seed=seed + index,
        )
        for index, baseline in enumerate(BASELINES)
    }

    fit_ids = sorted(
        incident_id
        for incident_id, split in assignments.items()
        if split in {"train", "validation"} and labels_by_id[incident_id]["training_eligible"]
    )
    permuted_model = fit_fixed(
        rows,
        fit_ids,
        selected_parameters,
        rounds=rounds,
        seed=seed,
        permute_labels_seed=seed + 991,
    )
    permuted = predict_rows(permuted_model, rows, test_nontrivial_ids)
    permuted_ranks = ranks_for_truth(permuted, labels_by_id)

    root_holdouts = {}
    for held_out_root in ("gateway", "orders", "payment"):
        train_ids = sorted(
            label["incident_id"]
            for label in fault_labels
            if label["training_eligible"] and label["root_service"] != held_out_root
        )
        test_ids = sorted(
            label["incident_id"]
            for label in fault_labels
            if label["training_eligible"] and label["root_service"] == held_out_root
        )
        holdout_model = fit_fixed(rows, train_ids, selected_parameters, rounds=rounds, seed=seed)
        holdout_rankings = predict_rows(holdout_model, rows, test_ids)
        holdout_ranks = ranks_for_truth(holdout_rankings, labels_by_id)
        root_faults = [label for label in fault_labels if label["root_service"] == held_out_root]
        root_holdouts[held_out_root] = {
            "train_incidents": len(train_ids),
            "test_incidents": len(test_ids),
            "detection_coverage": sum(label["detected"] for label in root_faults) / len(root_faults),
            "root_ready_coverage": sum(label["root_ready"] for label in root_faults) / len(root_faults),
            "metrics": rank_metrics(holdout_ranks.values()),
        }

    examples = _explain_examples(model, rows, labels_by_id, test_nontrivial_ids)
    real_ac1 = test_metrics["m7_lambdamart"]["ac_at_1"]
    permuted_metrics = rank_metrics(permuted_ranks.values())
    chance_ac1 = test_metrics["chance"]["ac_at_1"]
    no_permutation_leakage = permuted_metrics["ac_at_1"] < real_ac1 and permuted_metrics["ac_at_1"] <= chance_ac1 + 0.15
    no_baseline_regression = real_ac1 >= max(
        test_metrics["max_severity"]["ac_at_1"],
        test_metrics["local_evidence"]["ac_at_1"],
    )
    holdouts_survive = all(value["metrics"]["ac_at_1"] > 0 for value in root_holdouts.values())
    status = (
        "PROMISING"
        if real_ac1 > chance_ac1 + 0.15 and no_permutation_leakage and no_baseline_regression and holdouts_survive
        else "NOT YET JUSTIFIED"
    )
    return {
        "counts": {
            "fault_incidents": len(fault_labels),
            "healthy_controls": len(healthy_labels),
            "detected_fault_incidents": sum(label["detected"] for label in fault_labels),
            "root_ready_fault_incidents": sum(label["root_ready"] for label in fault_labels),
            "localization_eligible": sum(label["localization_eligible"] for label in fault_labels),
            "training_eligible": sum(label["training_eligible"] for label in fault_labels),
            "trivial_groups": sum(label["trivial_group"] for label in fault_labels),
            "test_localization_incidents": len(test_all_ids),
            "test_nontrivial_incidents": len(test_nontrivial_ids),
        },
        "detection": {
            "recall": sum(label["detected"] for label in fault_labels) / len(fault_labels),
            "root_ready_coverage": sum(label["root_ready"] for label in fault_labels) / len(fault_labels),
            "training_eligibility_rate": sum(label["training_eligible"] for label in fault_labels) / len(fault_labels),
            "healthy_false_positive_rate": sum(label["detected"] for label in healthy_labels) / len(healthy_labels),
        },
        "test_nontrivial_metrics": test_metrics,
        "test_all_localization_metrics": rank_metrics(learned_test_ranks.values()),
        "end_to_end_ac_at_1": end_to_end_successes / len(fault_labels),
        "paired_bootstrap_95_ci": paired,
        "label_permutation": {
            "real_label_ac_at_1": real_ac1,
            "permuted_label_ac_at_1": permuted_metrics["ac_at_1"],
            "permuted_metrics": permuted_metrics,
            "chance_ac_at_1": chance_ac1,
            "leakage_sanity_passed": no_permutation_leakage,
        },
        "root_holdout": root_holdouts,
        "feature_importance_gain": {
            column: float(model.get_score(importance_type="gain").get(column, 0.0))
            for column in FEATURE_COLUMNS
        },
        "prediction_examples": examples,
        "learned_model_candidate_status": status,
    }


def _baseline_rank(record: dict, truth: str, algorithm: str) -> int:
    rankings = record.get("m6_rankings", {}).get("rankings", {}).get(algorithm, [])
    return next((int(item["rank"]) for item in rankings if item["service"] == truth), 0)


def _chance_metrics(rows: Sequence[dict], incident_ids: Sequence[str]) -> dict[str, float]:
    sizes = [sum(row["incident_id"] == incident_id for row in rows) for incident_id in incident_ids]
    if not sizes:
        return {name: 0.0 for name in ("ac_at_1", "ac_at_3", "mrr", "ndcg_at_1", "ndcg_at_3")}
    return {
        "ac_at_1": sum(1 / size for size in sizes) / len(sizes),
        "ac_at_3": sum(min(3, size) / size for size in sizes) / len(sizes),
        "mrr": sum(sum(1 / rank for rank in range(1, size + 1)) / size for size in sizes) / len(sizes),
        "ndcg_at_1": sum(1 / size for size in sizes) / len(sizes),
        "ndcg_at_3": sum(
            sum(1 / math.log2(rank + 1) for rank in range(1, min(3, size) + 1)) / size for size in sizes
        )
        / len(sizes),
    }


def _explain_examples(
    model: xgb.Booster,
    rows: Sequence[dict],
    labels_by_id: dict[str, dict],
    test_ids: Sequence[str],
) -> list[dict]:
    examples = []
    for root, fault_type in (("payment", "latency"), ("orders", "error")):
        incident_id = next(
            (
                value
                for value in test_ids
                if labels_by_id[value]["root_service"] == root and labels_by_id[value]["fault_type"] == fault_type
            ),
            None,
        )
        if incident_id is None:
            continue
        matrix, _, groups, selected = matrix_for_incidents(rows, [incident_id])
        data = dmatrix(matrix, None, groups)
        scores = model.predict(data)
        contributions = model.predict(data, pred_contribs=True)
        ranking = sorted(
            ({"service": row["service"], "ml_score": float(score)} for row, score in zip(selected, scores, strict=True)),
            key=lambda item: (-item["ml_score"], item["service"]),
        )
        for rank, item in enumerate(ranking, 1):
            item["rank"] = rank
        root_index = next(index for index, row in enumerate(selected) if row["service"] == root)
        pairs = sorted(
            (
                {"feature": feature, "contribution": float(contributions[root_index, index])}
                for index, feature in enumerate(FEATURE_COLUMNS)
            ),
            key=lambda item: (-abs(item["contribution"]), item["feature"]),
        )
        examples.append(
            {
                "incident_id": incident_id,
                "root_service": root,
                "fault_type": fault_type,
                "ranking": ranking,
                "root_top_pred_contributions": pairs[:8],
                "interpretation_warning": "TreeSHAP contributions explain model score, not causality.",
            }
        )
    return examples
