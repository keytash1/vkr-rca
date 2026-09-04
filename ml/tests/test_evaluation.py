from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rca_ml.dataset import build_candidate_rows
from rca_ml.evaluate import evaluate_experiment
from rca_ml.fixtures import fixture_dataset
from rca_ml.split import stratified_split
from rca_ml.train import load_model, select_and_train


class EvaluationPipelineTests(unittest.TestCase):
    def test_complete_evaluation_includes_permutation_and_holdouts(self) -> None:
        features, labels = fixture_dataset(incidents_per_pair=10, healthy_controls=4)
        assignments = stratified_split(labels, seed=23)
        rows = build_candidate_rows(features, labels, assignments)
        labels_by_id = {label["incident_id"]: label for label in labels}
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.json"
            training = select_and_train(
                rows,
                labels_by_id,
                assignments,
                model_path,
                seed=23,
                max_rounds=20,
                early_stopping_rounds=4,
            )
            result = evaluate_experiment(
                features,
                labels,
                rows,
                assignments,
                load_model(model_path),
                selected_parameters=training["selected_hyperparameters"],
                rounds=training["training_rounds"],
                seed=23,
            )
        self.assertEqual(set(result["root_holdout"]), {"gateway", "orders", "payment"})
        self.assertIn("permuted_label_ac_at_1", result["label_permutation"])
        self.assertIn("hybrid_v1", result["paired_bootstrap_95_ci"])
        self.assertGreater(result["counts"]["test_nontrivial_incidents"], 0)


if __name__ == "__main__":
    unittest.main()
