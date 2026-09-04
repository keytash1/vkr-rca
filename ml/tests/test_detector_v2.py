import math
import unittest

import numpy as np

from rca_ml.detector_v2 import (
    FEATURE_SCHEMA_VERSION,
    Config,
    detect_operation,
    error_z,
    finite_output,
    positive_cusum,
    robust_residuals,
    sliding_stat,
)
from rca_ml.m9a_synthetic import corpus, evaluate, select_config, v1_evaluate
from rca_ml.m9a_experiment import evaluate_external


class DetectorV2Tests(unittest.TestCase):
    def test_robust_residuals_are_positive_only_and_finite(self):
        values, stats = robust_residuals([9, 10, 11, 10, 10], [5, 10, 20])
        self.assertEqual(values[0], 0)
        self.assertTrue(values[2] > values[1])
        self.assertTrue(all(math.isfinite(value) for value in values))
        self.assertGreaterEqual(stats["scale"], 0.1)

    def test_sliding_windows_and_edges(self):
        indices, values = sliding_stat([1, 2, 3, 4], 3, "median")
        self.assertEqual(indices.tolist(), [2, 3])
        self.assertEqual(values.tolist(), [2, 3])
        self.assertEqual(sliding_stat([1, 2], 3, "median")[1].size, 0)

    def test_tail_quantile(self):
        _, values = sliding_stat([0, 0, 0, 10, 20], 5, "quantile", 0.9)
        self.assertAlmostEqual(values[0], 16.0)

    def test_cusum_exact_sequence(self):
        self.assertEqual(positive_cusum([0, 1, 2, 0], 0.5).tolist(), [0, 0.5, 2.0, 1.5])

    def test_temporal_profiles_cover_late_burst_ramp_and_intermittent(self):
        records = corpus()
        selected = select_config(records)["selected_config"]
        validation = [row for row in records if row["split"] == "validation"]
        v1, v2 = v1_evaluate(validation), evaluate(validation, selected)
        for profile in ("step_late", "burst", "ramp", "intermittent"):
            self.assertGreaterEqual(v2["by_profile"][profile], v1["by_profile"][profile])

    def test_error_channel_and_missing_evidence(self):
        self.assertIsNotNone(error_z([False] * 100, [True] * 10))
        self.assertIsNone(error_z([None] * 100, [None] * 10))
        result = detect_operation([10] * 100, [10] * 20, [None] * 100, [None] * 20, Config())
        self.assertFalse(result["error_channel_available"])
        self.assertIsNone(result["error_temporal_score"])

    def test_partial_error_evidence_is_used_and_matches_exact_windows(self):
        baseline = [False, None, False, False, None] * 20
        current = [None, True, True, None, False] * 4
        config = Config(variant="cusum", windows=(5,), cusum_threshold=1_000_000)
        result = detect_operation([10] * 100, [10] * 20, baseline, current, config)
        expected = max(float(error_z(baseline, current[end - 5:end]) or 0.0) for end in range(5, 21))
        self.assertTrue(result["error_channel_available"])
        self.assertAlmostEqual(result["error_temporal_score"], expected)
        self.assertTrue(result["anomalous"])

    def test_selection_and_split_are_deterministic(self):
        records = corpus()
        first, second = select_config(records), select_config(records)
        self.assertEqual(first["selected_config"].digest(), second["selected_config"].digest())
        self.assertEqual(first["scenario_overlap"], [])
        self.assertLessEqual(first["selected_metrics"]["healthy_fpr"], 0.10)

    def test_output_schema_is_finite_and_repeatable(self):
        config = Config()
        args = ([10] * 100, [10, 12, 40, 10, 10] * 4, [False] * 100, [False] * 20, config)
        first, second = detect_operation(*args), detect_operation(*args)
        self.assertEqual(first, second)
        self.assertEqual(first["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertTrue(finite_output(first))
        for key in ("location_score", "tail_score", "cusum_score", "error_temporal_score", "onset_fraction",
                    "persistence_fraction", "max_exceedance_run", "selected_scale"):
            self.assertIn(key, first)

    def test_external_labels_cannot_join_before_truth_free_seal(self):
        with self.assertRaisesRegex(ValueError, "sealed truth-free"):
            evaluate_external([], [], {"sealed_before_label_join": False})


if __name__ == "__main__":
    unittest.main()
