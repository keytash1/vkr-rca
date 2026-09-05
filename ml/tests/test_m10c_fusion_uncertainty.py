import unittest

from rca_ml.m10c_fusion import build_meta_rows, simple_fusion
from rca_ml.m10c_uncertainty import (
    assert_disjoint_partitions, calibrate_abstention, conformal_quantile, evaluate_abstention,
    evaluate_conformal, prediction_set,
)


def ranking(incident, order, truth):
    return [{"service": service, "score": len(order) - i, "rank": i + 1,
             "label": int(service == truth)} for i, service in enumerate(order)]


class M10CFusionUncertaintyTests(unittest.TestCase):
    def test_split_conformal_partitions_are_disjoint(self):
        assert_disjoint_partitions(["fit"], ["cal"], ["test"])
        with self.assertRaisesRegex(ValueError, "disjoint"):
            assert_disjoint_partitions(["same"], ["same"], ["test"])

    def test_late_fusion_uses_masks_and_disagreement(self):
        metric = {"i": ranking("i", ["a", "b"], "a")}
        trace = {"i": ranking("i", ["b", "a"], "a")}
        rows = []
        for service, label in (("a", 1), ("b", 0)):
            rows.append({"incident_id": "i", "service": service, "label": label,
                         "coverage_has_metrics": 1, "coverage_has_traces": service == "b",
                         "coverage_has_topology": 0, "coverage_metric_family_ratio": .5,
                         "trace_trace_coverage": .4, "topology_normalized_in_degree": 0,
                         "topology_normalized_out_degree": 0})
        meta = build_meta_rows(metric, trace, rows)
        self.assertGreater(meta[0]["expert_disagreement"], 0)
        self.assertIn("has_traces", meta[0])
        self.assertEqual(simple_fusion(metric, trace, "rrf"), simple_fusion(metric, trace, "rrf"))

    def test_split_conformal_is_rank_normalized(self):
        calibration = {
            "a": ranking("a", ["x", "y"], "x"),
            "b": ranking("b", ["x", "y", "z", "q"], "y"),
        }
        q = conformal_quantile(calibration, .9)
        self.assertEqual(q, .5)
        self.assertEqual(prediction_set(calibration["b"], q), ["x", "y"])
        result = evaluate_conformal(calibration, calibration, .9)
        self.assertEqual(result["empirical_coverage"], 1)

    def test_abstention_threshold_is_calibration_only(self):
        calibration = [
            {"quality": .9, "correct": True, "truth_rank": 1},
            {"quality": .8, "correct": True, "truth_rank": 1},
            {"quality": .2, "correct": False, "truth_rank": 2},
        ]
        policy = calibrate_abstention(calibration, .9)
        self.assertEqual(policy["calibration_coverage"], 2 / 3)
        result = evaluate_abstention(calibration, policy["threshold"])
        self.assertEqual(result["selective_ac_at_1"], 1)
        self.assertGreaterEqual(result["aurc"], 0)


if __name__ == "__main__":
    unittest.main()
