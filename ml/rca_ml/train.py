"""XGBoost LambdaMART model selection and final fitting."""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import matrix_for_incidents, rankings_from_scores, ranks_for_truth
from .metrics import rank_metrics
from .schema import FEATURE_COLUMNS


SEARCH_SPACE = tuple(
    {"max_depth": depth, "eta": eta, "min_child_weight": child, "subsample": 0.8, "colsample_bytree": 0.8}
    for depth, eta, child in itertools.product((2, 3), (0.03, 0.1), (1, 5))
)


def base_parameters(seed: int) -> dict:
    return {
        "objective": "rank:ndcg",
        "eval_metric": ["ndcg@1", "ndcg@3"],
        "tree_method": "hist",
        "lambdarank_pair_method": "topk",
        "lambdarank_num_pair_per_sample": 3,
        "seed": seed,
        "nthread": 4,
    }


def dmatrix(matrix: np.ndarray, labels: np.ndarray | None, groups: Sequence[int]) -> xgb.DMatrix:
    data = xgb.DMatrix(matrix, label=labels, feature_names=list(FEATURE_COLUMNS))
    data.set_group(np.asarray(groups, dtype=np.uint32))
    return data


def select_and_train(
    rows: Sequence[dict],
    labels_by_id: dict[str, dict],
    assignments: dict[str, str],
    model_path: str | Path,
    *,
    seed: int,
    max_rounds: int = 200,
    early_stopping_rounds: int = 20,
) -> dict:
    train_ids = sorted(
        incident_id
        for incident_id, split in assignments.items()
        if split == "train" and labels_by_id[incident_id].get("training_eligible")
    )
    validation_ids = sorted(
        incident_id
        for incident_id, split in assignments.items()
        if split == "validation" and labels_by_id[incident_id].get("training_eligible")
    )
    if not train_ids or not validation_ids:
        raise ValueError("train and validation need non-trivial eligible incidents")
    train_matrix, train_target, train_groups, _ = matrix_for_incidents(rows, train_ids)
    val_matrix, val_target, val_groups, val_rows = matrix_for_incidents(rows, validation_ids)
    train_data = dmatrix(train_matrix, train_target, train_groups)
    val_data = dmatrix(val_matrix, val_target, val_groups)
    search = []
    for candidate in SEARCH_SPACE:
        parameters = {**base_parameters(seed), **candidate}
        history: dict = {}
        booster = xgb.train(
            parameters,
            train_data,
            num_boost_round=max_rounds,
            evals=[(train_data, "train"), (val_data, "validation")],
            evals_result=history,
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False,
        )
        best_iteration = int(booster.best_iteration)
        scores = booster.predict(val_data, iteration_range=(0, best_iteration + 1))
        rankings = rankings_from_scores(val_rows, scores)
        ranks = ranks_for_truth(rankings, labels_by_id)
        metrics = rank_metrics(ranks.values())
        search.append(
            {
                "hyperparameters": candidate,
                "best_iteration": best_iteration,
                "best_validation_ndcg_at_3": float(booster.best_score),
                "validation_metrics": metrics,
            }
        )
    search.sort(key=_selection_key)
    selected = search[0]
    combined_ids = sorted(train_ids + validation_ids)
    matrix, target, groups, _ = matrix_for_incidents(rows, combined_ids)
    final_data = dmatrix(matrix, target, groups)
    final_parameters = {**base_parameters(seed), **selected["hyperparameters"]}
    rounds = selected["best_iteration"] + 1
    final_model = xgb.train(final_parameters, final_data, num_boost_round=rounds, verbose_eval=False)
    destination = Path(model_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(destination)
    return {
        "search": search,
        "selected_hyperparameters": selected["hyperparameters"],
        "best_iteration": selected["best_iteration"],
        "training_rounds": rounds,
        "best_validation_metrics": selected["validation_metrics"],
        "best_validation_ndcg_at_3": selected["best_validation_ndcg_at_3"],
        "train_incidents": len(train_ids),
        "validation_incidents": len(validation_ids),
    }


def fit_fixed(
    rows: Sequence[dict],
    incident_ids: Sequence[str],
    parameters: dict,
    *,
    rounds: int,
    seed: int,
    permute_labels_seed: int | None = None,
) -> xgb.Booster:
    matrix, target, groups, _ = matrix_for_incidents(rows, incident_ids)
    if permute_labels_seed is not None:
        target = permuted_query_labels(target, groups, permute_labels_seed)
    data = dmatrix(matrix, target, groups)
    return xgb.train({**base_parameters(seed), **parameters}, data, num_boost_round=rounds, verbose_eval=False)


def predict_rows(model: xgb.Booster, rows: Sequence[dict], incident_ids: Sequence[str]) -> dict[str, list[dict]]:
    matrix, _, groups, selected = matrix_for_incidents(rows, incident_ids)
    data = dmatrix(matrix, None, groups)
    return rankings_from_scores(selected, model.predict(data))


def permuted_query_labels(target: np.ndarray, groups: Sequence[int], seed: int) -> np.ndarray:
    import random

    result = np.zeros_like(target)
    randomizer = random.Random(seed)
    offset = 0
    for group_size in groups:
        original = int(np.argmax(target[offset : offset + group_size]))
        choices = [index for index in range(group_size) if index != original]
        selected = randomizer.choice(choices) if choices else original
        result[offset + selected] = 1
        offset += group_size
    return result


def load_model(path: str | Path) -> xgb.Booster:
    model = xgb.Booster()
    model.load_model(Path(path))
    return model


def save_json(path: str | Path, value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selection_key(result: dict) -> tuple:
    metrics = result["validation_metrics"]
    parameters = result["hyperparameters"]
    return (
        -metrics["mrr"],
        -metrics["ac_at_1"],
        -metrics["ndcg_at_1"],
        parameters["max_depth"],
        -parameters["eta"],
        parameters["min_child_weight"],
    )
