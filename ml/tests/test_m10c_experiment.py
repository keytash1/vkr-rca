import unittest

from rca_ml.m10c_experiment import feature_group, masked_rows
from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C


class M10CExperimentTests(unittest.TestCase):
    def test_feature_groups_are_predeclared(self):
        self.assertEqual(feature_group("metric_cpu_max_shift"), "cpu")
        self.assertEqual(feature_group("workload_residual_peak"), "workload")
        self.assertEqual(feature_group("trace_error_z_log1p"), "trace")
        self.assertEqual(feature_group("coverage_has_metrics"), "coverage")

    def test_missingness_is_label_blind_and_keeps_candidates(self):
        row = {name: 1.0 for name in FEATURE_COLUMNS_M10C}
        row.update({"incident_id": "i", "service": "s", "label": 1})
        masked = masked_rows([row], "metrics_missing")[0]
        self.assertEqual(masked["incident_id"], "i")
        self.assertEqual(masked["service"], "s")
        self.assertEqual(masked["label"], 1)
        self.assertEqual(masked["metric_cpu_max_shift"], 0)
        self.assertEqual(masked["trace_error_z_log1p"], 1)


if __name__ == "__main__":
    unittest.main()

