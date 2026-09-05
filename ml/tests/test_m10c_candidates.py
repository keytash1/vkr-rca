import unittest

import numpy as np
import pandas as pd

from rca_ml.m10c_candidates import RCAEvalFrameSource, generate_candidates, resolve_metric_entity
from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C, validate_schema


class M10CCandidateTests(unittest.TestCase):
    def test_metric_only_candidate_survives_trace_blind_spot(self):
        frame = pd.DataFrame({"time": np.arange(4), "adservice_cpu": [1, 2, 3, 4]})
        source = RCAEvalFrameSource(frame)
        candidates = {item.name: item for item in generate_candidates(source, ["frontend"], ["frontend"])}
        self.assertIn("adservice", candidates)
        self.assertTrue(candidates["adservice"].has_metrics)
        self.assertFalse(candidates["adservice"].has_traces)

    def test_union_deduplicates_normalized_metric_and_trace_names(self):
        frame = pd.DataFrame({"time": [1], "orders_service_cpu": [1], "payment_cpu": [2]})
        source = RCAEvalFrameSource(frame)
        candidates = generate_candidates(source, ["orders", "gateway"])
        self.assertEqual([item.name for item in candidates], ["gateway", "orders", "payment"])

    def test_infrastructure_is_typed_out_without_root_labels(self):
        frame = pd.DataFrame({"time": [1], "orders_cpu": [1], "redis_cpu": [9]})
        names = [item.name for item in generate_candidates(RCAEvalFrameSource(frame), [])]
        self.assertEqual(names, ["orders"])

    def test_generic_adapter_registry_and_series(self):
        frame = pd.DataFrame({"time": [1, 2], "checkout_reqps": [3, 4]})
        source = RCAEvalFrameSource(frame, {"reqps": "traffic_rate"})
        self.assertEqual(source.list_families(), ("traffic_rate",))
        self.assertEqual(source.list_entities(), ("checkout",))
        series = source.read_series("checkout", "traffic_rate")[0]
        self.assertEqual(series.source_name, "checkout_reqps")
        self.assertEqual(series.values.tolist(), [3.0, 4.0])

    def test_ambiguous_or_absent_trace_mapping_keeps_canonical_entity(self):
        self.assertEqual(resolve_metric_entity("emailservice", ["frontend"]), "emailservice")
        self.assertEqual(resolve_metric_entity("orders_service", ["orders"]), "orders")

    def test_compact_schema_is_deterministic_and_reduced(self):
        validate_schema()
        self.assertEqual(len(FEATURE_COLUMNS_M10C), 90)
        self.assertLessEqual(len(FEATURE_COLUMNS_M10C), 253 // 2)


if __name__ == "__main__":
    unittest.main()

