"""Generic deterministic LambdaMART helpers for M9B feature subsets."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Sequence

import numpy as np
import xgboost as xgb

from .metrics import rank_metrics

SEED = 20260904
SEARCH_SPACE = (
    {"max_depth": 2, "eta": .1, "min_child_weight": 1, "subsample": .8, "colsample_bytree": .8},
    {"max_depth": 2, "eta": .03, "min_child_weight": 1, "subsample": .8, "colsample_bytree": .8},
    {"max_depth": 3, "eta": .1, "min_child_weight": 1, "subsample": .8, "colsample_bytree": .8},
    {"max_depth": 3, "eta": .03, "min_child_weight": 5, "subsample": .8, "colsample_bytree": .8},
)


def incident_split(incident_ids: Sequence[str], namespace: str, validation_modulus: int = 5) -> tuple[list[str], list[str]]:
    train, validation = [], []
    for incident_id in sorted(incident_ids):
        digest = int(hashlib.sha256(f"{namespace}:{incident_id}".encode()).hexdigest(), 16)
        (validation if digest % validation_modulus == 0 else train).append(incident_id)
    if not train or not validation:
        raise ValueError("deterministic split produced an empty partition")
    return train, validation


def select_hyperparameters(rows: list[dict], incident_ids: Sequence[str], columns: Sequence[str], namespace: str) -> dict:
    train_ids, validation_ids = incident_split(incident_ids, namespace)
    train = _dmatrix(rows, train_ids, columns, labels=True)
    validation = _dmatrix(rows, validation_ids, columns, labels=True)
    results = []
    for candidate in SEARCH_SPACE:
        history = {}
        model = xgb.train(
            {**_base_parameters(), **candidate}, train[0], num_boost_round=120,
            evals=[(train[0], "train"), (validation[0], "validation")], evals_result=history,
            early_stopping_rounds=15, verbose_eval=False,
        )
        iteration = int(model.best_iteration)
        rankings = predict_rankings(model, validation[3], validation[0], iteration + 1)
        metrics = metrics_for_rankings(rankings)
        results.append({"hyperparameters": candidate, "best_iteration": iteration,
                        "training_rounds": iteration + 1, "validation": metrics})
    results.sort(key=lambda value: (-value["validation"]["mrr"], -value["validation"]["ac_at_1"],
                                    value["hyperparameters"]["max_depth"], -value["hyperparameters"]["eta"],
                                    value["hyperparameters"]["min_child_weight"]))
    return {"train_incidents": len(train_ids), "validation_incidents": len(validation_ids),
            "selected": results[0], "search": results}


def fit_fixed(rows: list[dict], incident_ids: Sequence[str], columns: Sequence[str], hyperparameters: dict,
              rounds: int, destination: str | Path | None = None) -> xgb.Booster:
    data = _dmatrix(rows, incident_ids, columns, labels=True)[0]
    model = xgb.train({**_base_parameters(), **hyperparameters}, data, num_boost_round=rounds, verbose_eval=False)
    if destination is not None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(path)
    return model


def evaluate_model(model: xgb.Booster, rows: list[dict], incident_ids: Sequence[str], columns: Sequence[str],
                   rounds: int | None = None) -> tuple[dict, dict[str, list[dict]]]:
    data, _, _, selected = _dmatrix(rows, incident_ids, columns, labels=False)
    rankings = predict_rankings(model, selected, data, rounds)
    return metrics_for_rankings(rankings), rankings


def predict_rankings(model: xgb.Booster, rows: list[dict], data: xgb.DMatrix, rounds: int | None = None) -> dict[str, list[dict]]:
    scores = model.predict(data, iteration_range=(0, rounds) if rounds else (0, 0))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        grouped[row["incident_id"]].append({"service": row["service"], "score": float(score),
                                             "label": int(row["label"])})
    for ranking in grouped.values():
        ranking.sort(key=lambda value: (-value["score"], value["service"]))
        for position, value in enumerate(ranking, 1):
            value["rank"] = position
    return dict(grouped)


def metrics_for_rankings(rankings: dict[str, list[dict]]) -> dict:
    ranks = [next(value["rank"] for value in ranking if value["label"] == 1) for ranking in rankings.values()]
    return {"cases": len(ranks), **rank_metrics(ranks)}


def truth_ranks(rankings: dict[str, list[dict]]) -> dict[str, int]:
    return {incident: next(value["rank"] for value in ranking if value["label"] == 1)
            for incident, ranking in rankings.items()}


def contributions(model: xgb.Booster, rows: list[dict], incident_id: str, columns: Sequence[str]) -> list[dict]:
    data, _, _, selected = _dmatrix(rows, [incident_id], columns, labels=False)
    values = model.predict(data, pred_contribs=True)
    result = []
    for row, contribution in zip(selected, values, strict=True):
        ranked = sorted(zip(columns, contribution[:-1], strict=True), key=lambda value: -abs(float(value[1])))[:10]
        result.append({"service": row["service"], "truth": bool(row["label"]),
                       "top_contributions": [{"feature": name, "value": float(score)} for name, score in ranked]})
    return result


def _dmatrix(rows: list[dict], incident_ids: Sequence[str], columns: Sequence[str], labels: bool) -> tuple[xgb.DMatrix, np.ndarray, list[int], list[dict]]:
    wanted = set(incident_ids)
    selected = sorted((row for row in rows if row["incident_id"] in wanted),
                      key=lambda value: (value["incident_id"], value["service"]))
    groups = []
    previous = None
    for row in selected:
        if row["incident_id"] != previous:
            groups.append(0)
            previous = row["incident_id"]
        groups[-1] += 1
    matrix = np.asarray([[float(row[name]) for name in columns] for row in selected], dtype=np.float32)
    target = np.asarray([int(row["label"]) for row in selected], dtype=np.float32)
    if not len(selected) or not all(sum(row["label"] for row in selected if row["incident_id"] == incident) == 1 for incident in wanted):
        raise ValueError("each selected M9B incident needs exactly one observable root")
    data = xgb.DMatrix(matrix, label=target if labels else None, feature_names=list(columns))
    data.set_group(np.asarray(groups, dtype=np.uint32))
    return data, target, groups, selected


def _base_parameters() -> dict:
    return {"objective": "rank:ndcg", "eval_metric": ["ndcg@1", "ndcg@3"], "tree_method": "hist",
            "lambdarank_pair_method": "topk", "lambdarank_num_pair_per_sample": 3,
            "seed": SEED, "nthread": 4}
