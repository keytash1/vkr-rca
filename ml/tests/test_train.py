from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rca_ml.dataset import build_candidate_rows, matrix_for_incidents
from rca_ml.fixtures import fixture_dataset
from rca_ml.split import stratified_split
from rca_ml.train import (
    fit_fixed,
    load_model,
    permuted_query_labels,
    predict_rows,
    select_and_train,
)


class TrainingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.features, self.labels = fixture_dataset(incidents_per_pair=10)
        self.assignments = stratified_split(self.labels, seed=11)
        self.rows = build_candidate_rows(self.features, self.labels, self.assignments)
        self.labels_by_id = {label["incident_id"]: label for label in self.labels}

    def test_tiny_lambdamart_train_and_prediction_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            result = select_and_train(
                self.rows,
                self.labels_by_id,
                self.assignments,
                path,
                seed=11,
                max_rounds=20,
                early_stopping_rounds=4,
            )
            model = load_model(path)
            test_ids = sorted(key for key, value in self.assignments.items() if value == "test")
            self.assertEqual(predict_rows(model, self.rows, test_ids), predict_rows(model, self.rows, test_ids))
            self.assertEqual(result["selected_hyperparameters"]["subsample"], 0.8)

    def test_label_permutation_keeps_one_positive_per_query(self) -> None:
        ids = sorted(
            key
            for key, value in self.assignments.items()
            if value == "train" and self.labels_by_id[key]["training_eligible"]
        )
        _, target, groups, _ = matrix_for_incidents(self.rows, ids)
        permuted = permuted_query_labels(target, groups, seed=4)
        offset = 0
        for size in groups:
            self.assertEqual(sum(permuted[offset : offset + size]), 1)
            offset += size

    def test_root_holdout_model_accepts_unseen_root_identity(self) -> None:
        train_ids = [
            label["incident_id"]
            for label in self.labels
            if label["training_eligible"] and label["root_service"] != "payment"
        ]
        test_ids = [
            label["incident_id"]
            for label in self.labels
            if label["training_eligible"] and label["root_service"] == "payment"
        ]
        model = fit_fixed(
            self.rows,
            train_ids,
            {"max_depth": 2, "eta": 0.1, "min_child_weight": 1, "subsample": 1, "colsample_bytree": 1},
            rounds=10,
            seed=1,
        )
        self.assertEqual(len(predict_rows(model, self.rows, test_ids)), len(test_ids))


if __name__ == "__main__":
    unittest.main()
