import unittest
from rca_ml.r3_red import UNITS, evidence, fit_healthy, fuse, average_ranks


class REDTests(unittest.TestCase):
    services = ("a", "b")

    def records(self, **changes):
        data = {"request_rate": 5., "error_ratio": 0., "latency_p95": .01} | changes
        return [{"service": s, "channel": c, "unit": u, "timestamp": 10., "value": data[c]}
                for s in self.services for c, u in UNITS.items()]

    def test_units_unknown_fields_and_duplicate_series(self):
        for change in ({"unit": "milliseconds"}, {"root": "a"}, {"value": float("nan")}, {"timestamp": True}):
            data = self.records(); data[0] = data[0] | change
            with self.assertRaises(ValueError): fit_healthy(data, self.services)
        data = self.records()
        with self.assertRaises(ValueError): fit_healthy(data + [data[0]], self.services)
        with self.assertRaises(ValueError): fit_healthy(self.records(error_ratio=10), self.services)

    def test_idle_missing_and_stale_zero_are_distinct(self):
        baseline = fit_healthy(self.records(), self.services)
        available = dict.fromkeys(self.services, "available")
        idle = self.records(request_rate=0, error_ratio=None, latency_p95=None)
        self.assertEqual(set(evidence(idle, baseline, self.services, available)["states"].values()), {"no_activity"})
        stale = evidence(idle, baseline, self.services, dict.fromkeys(self.services, "unavailable"))
        self.assertEqual(set(stale["states"].values()), {"source_unavailable"})
        self.assertFalse(stale["eligible_for_fusion"])
        missing = evidence([], baseline, self.services, available)
        self.assertEqual(set(missing["states"].values()), {"unavailable"})
        with self.assertRaises(ValueError): evidence(idle, baseline, self.services, {})

    def test_no_signal_keeps_model_order_and_ties_do_not_use_identity(self):
        base = fit_healthy(self.records(), self.services)
        result = evidence(self.records(), base, self.services, dict.fromkeys(self.services, "available"))
        ranking = [{"service": "b", "rank": 1, "score": 2.}, {"service": "a", "rank": 2, "score": 1.}]
        self.assertEqual(fuse(ranking, result), ranking)
        self.assertIsNot(fuse(ranking, result)[0], ranking[0])
        self.assertEqual(average_ranks({"b": 10, "a": 10}), {"a": 1.5, "b": 1.5})


if __name__ == "__main__": unittest.main()
