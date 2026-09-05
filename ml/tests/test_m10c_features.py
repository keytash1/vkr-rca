import unittest

import numpy as np
import pandas as pd

from rca_ml.m10c_features import extract_features
from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C
from rca_ml.m10c_workload import conditioned_residual_features
from rca_ml.m10c_candidates import RCAEvalFrameSource


class M10CFeatureTests(unittest.TestCase):
    def test_feature_vector_covers_union_with_explicit_masks(self):
        times = np.arange(1200, dtype=float)
        frame = pd.DataFrame({
            "time": times,
            "orders_load": 10 + times / 100,
            "orders_cpu": np.where(times < 600, 20 + times / 100, 90),
            "payment_cpu": np.ones(1200),
        })
        trace = {"services": [{
            "service": "gateway", "vector": {"has_trace": 1, "trace_latency_z_log1p": 2,
                                                "trace_in_degree": 1}
        }]}
        result = extract_features(frame, 600, trace)
        self.assertEqual(result["candidate_services"], ["gateway", "orders", "payment"])
        vectors = {item["service"]: item["vector"] for item in result["services"]}
        self.assertEqual(set(vectors["orders"]), set(FEATURE_COLUMNS_M10C))
        self.assertEqual(vectors["orders"]["coverage_has_metrics"], 1)
        self.assertEqual(vectors["orders"]["coverage_has_traces"], 0)
        self.assertEqual(vectors["gateway"]["coverage_has_metrics"], 0)
        self.assertEqual(vectors["gateway"]["coverage_has_traces"], 1)

    def test_workload_fit_is_baseline_only_and_detects_residual(self):
        times = np.arange(1200, dtype=float)
        load = 1 + times / 100
        cpu = 2 * load + 3
        cpu[600:] += 20
        frame = pd.DataFrame({"time": times, "orders_load": load, "orders_cpu": cpu})
        result = conditioned_residual_features(RCAEvalFrameSource(frame), "orders", 600)
        self.assertGreater(result["workload_residual_location"], 3.5)
        self.assertGreater(result["workload_residual_persistence"], .9)


if __name__ == "__main__":
    unittest.main()

