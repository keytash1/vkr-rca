import copy
import unittest
from rca_ml.r3_temporal import temporal_features, temporal_heuristic


class TemporalContract(unittest.TestCase):
    def setUp(self):
        self.window = {"start_unix": 0, "end_unix": 12, "requests_per_second": 1,
                       "metrics": [{"service": "a", "family": "cpu", "timestamp": 1, "value": 8},
                                   {"service": "a", "family": "cpu", "timestamp": 10, "value": 2}],
                       "traces": [{"service": "b", "start_time_us": 2_000_000, "error": True}],
                       "traces_collected": True}
        self.baseline = {"metric": {s: {"cpu": {"intercept": 0, "slope": 0, "residual_iqr": 1}} for s in ("a", "b")}}

    def test_order_invariance(self):
        expected = temporal_features(self.window, self.baseline, ("a", "b"))
        other = copy.deepcopy(self.window)
        other["metrics"].reverse()
        other["traces"].reverse()
        self.assertEqual(expected, temporal_features(other, self.baseline, ("b", "a")))
        self.assertEqual(expected["a"]["time_metric_first_fraction"], 1 / 12)

    def test_identity_is_only_join(self):
        old = temporal_features(self.window, self.baseline, ("a", "b"))
        other, baseline = copy.deepcopy(self.window), copy.deepcopy(self.baseline)
        aliases = {"a": "zz", "b": "qq"}
        for key in ("metrics", "traces"):
            for point in other[key]:
                point["service"] = aliases[point["service"]]
        baseline["metric"] = {aliases[k]: v for k, v in baseline["metric"].items()}
        new = temporal_features(other, baseline, tuple(aliases.values()))
        self.assertEqual({aliases[k]: v for k, v in old.items()}, new)

    def test_missing_not_observed(self):
        self.window["metrics"] = []
        self.window["traces"] = []
        self.window["traces_collected"] = False
        out = temporal_features(self.window, self.baseline, ("a", "b"))
        self.assertEqual(out["a"]["time_trace_error_observed"], 0)
        self.assertEqual(out["a"]["time_metric_deviation_observed"], 0)
        self.assertEqual(len(temporal_heuristic(out, {"a": 0, "b": 0})), 2)

    def test_truth_rejected(self):
        for name in ("root_service", "fault_family", "incident_id", "workload_result", "system"):
            with self.assertRaises(ValueError):
                temporal_features(dict(self.window, **{name: "answer"}), self.baseline, ("a", "b"))

    def test_boundaries_and_invalid_values(self):
        self.window["metrics"].append({"service": "a", "family": "cpu", "timestamp": -1, "value": 100})
        f = temporal_features(self.window, self.baseline, ("a", "b"))["a"]
        self.assertEqual(f["time_metric_early_shift"], 8)
        self.window["metrics"][0]["value"] = float("nan")
        with self.assertRaises(ValueError):
            temporal_features(self.window, self.baseline, ("a", "b"))


if __name__ == "__main__":
    unittest.main()
