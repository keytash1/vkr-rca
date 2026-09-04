from __future__ import annotations

import unittest

from rca_ml.fixtures import fixture_dataset
from rca_ml.metrics import paired_bootstrap, rank_metrics
from rca_ml.split import root_holdout, stratified_split


class MetricsSplitTests(unittest.TestCase):
    def test_metric_values_include_missing_rank(self) -> None:
        metrics = rank_metrics([1, 2, 0], total=3)
        self.assertAlmostEqual(metrics["ac_at_1"], 1 / 3)
        self.assertAlmostEqual(metrics["ac_at_3"], 2 / 3)
        self.assertAlmostEqual(metrics["mrr"], 0.5)
        self.assertAlmostEqual(metrics["ndcg_at_1"], 1 / 3)

    def test_bootstrap_is_deterministic(self) -> None:
        first = paired_bootstrap([1, 1, 2, 1], [2, 1, 3, 2], resamples=100, seed=9)
        second = paired_bootstrap([1, 1, 2, 1], [2, 1, 3, 2], resamples=100, seed=9)
        self.assertEqual(first, second)

    def test_root_holdout_construction(self) -> None:
        _, labels = fixture_dataset()
        train, test = root_holdout(labels, "payment")
        by_id = {label["incident_id"]: label for label in labels}
        self.assertTrue(train and test)
        self.assertTrue(all(by_id[value]["root_service"] != "payment" for value in train))
        self.assertTrue(all(by_id[value]["root_service"] == "payment" for value in test))

    def test_split_has_all_three_partitions(self) -> None:
        _, labels = fixture_dataset(incidents_per_pair=10)
        assignments = stratified_split(labels, seed=3)
        self.assertEqual(set(assignments.values()), {"train", "validation", "test"})


if __name__ == "__main__":
    unittest.main()
