import tempfile
import unittest
from pathlib import Path

from rca_ml.m10a_analysis import (
    feature_group,
    full_denominator_metrics,
    immutable_hashes,
    percentile,
    smoke,
    summarize_seed_values,
)


class M10ATests(unittest.TestCase):
    def test_full_denominator_counts_unobservable_as_failure(self):
        result = full_denominator_metrics({"a": 1, "b": 2}, ["a", "b", "c", "d"])
        self.assertEqual(result["cases"], 4)
        self.assertEqual(result["missing_failures"], 2)
        self.assertEqual(result["ac_at_1"], .25)
        self.assertEqual(result["ac_at_3"], .5)

    def test_seed_summary_is_deterministic(self):
        first = summarize_seed_values([.4, .5, .6, .7, .8], 42, resamples=1000)
        second = summarize_seed_values([.4, .5, .6, .7, .8], 42, resamples=1000)
        self.assertEqual(first, second)
        self.assertEqual(first["mean"], .6)

    def test_feature_group_mapping(self):
        self.assertEqual(feature_group("metric_cpu_max_shift"), "cpu")
        self.assertEqual(feature_group("metric_memory_has"), "memory")
        self.assertEqual(feature_group("metric_disk_io_p90_shift_z"), "disk")
        self.assertEqual(feature_group("metric_latency_p90_max_shift"), "latency")
        self.assertEqual(feature_group("metric_max_shift_score"), "cross_family")
        self.assertEqual(feature_group("trace_latency_z_log1p"), "trace")
        self.assertEqual(feature_group("trace_topology_f1"), "topology")

    def test_percentile_uses_locked_nearest_index(self):
        self.assertEqual(percentile([0, 1, 2, 3, 4], .5), 2)

    def test_immutable_hashes_detect_change_without_writing_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models = root / "models"; docs = root / "docs"
            models.mkdir(); docs.mkdir()
            (models / "evaluation.json").write_text("one")
            (docs / "m9b-results.md").write_text("two")
            (docs / "rca-v1.md").write_text("three")
            first = immutable_hashes(models, docs)
            (docs / "m9b-results.md").write_text("changed")
            self.assertNotEqual(first, immutable_hashes(models, docs))

    def test_smoke(self):
        result = smoke()
        self.assertEqual(result["research_mutation"], "none")
        self.assertGreater(result["paired"]["ac_at_1"]["difference"], 0)


if __name__ == "__main__":
    unittest.main()
