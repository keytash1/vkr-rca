import copy
import unittest

from rca_ml.r3_red import UNITS, fit_healthy
from rca_ml.r3_red_reserve import reserve


class ReserveTests(unittest.TestCase):
    services = ("a", "b", "c")
    ranking = [{"service": s, "rank": i, "score": 4-i} for i, s in enumerate(services, 1)]
    edges = [{"source": "a", "target": "b", "presence": 1.},
             {"source": "b", "target": "c", "presence": 1.}]

    def records(self, error=None, idle=()):
        return [{"service": s, "channel": c, "unit": unit, "timestamp": 1.,
                 "value": (0. if c == "request_rate" else None) if s in idle else
                          {"request_rate": 5., "latency_p95": .01, "error_ratio": (error or {}).get(s, 0.)}[c]}
                for s in self.services for c, unit in UNITS.items()]

    def run_reserve(self, records=None, **kwargs):
        args = dict(ranking=self.ranking, observations=records or self.records(),
                    healthy=fit_healthy(self.records(), self.services), services=self.services,
                    source_states=dict.fromkeys(self.services, "available"), edges=self.edges,
                    traces_available=False)
        args.update(kwargs)
        return reserve(**args)

    def test_no_full_trace_change_and_no_signal(self):
        for options in ({"traces_available": True}, {}):
            result = self.run_reserve(**options)
            self.assertFalse(result["applied"])
            self.assertEqual(result["ranking"], self.ranking)
            self.assertIsNot(result["ranking"][0], self.ranking[0])

    def test_propagated_symptom_frontier_and_idle_child(self):
        result = self.run_reserve(self.records(error={"a": 1., "b": 1.}, idle=("c",)))
        self.assertEqual(result["ranking"][0]["service"], "b")
        self.assertEqual(result["frontier"], ["b"])
        self.assertEqual(result["states"]["c"], "no_activity")
        root = self.run_reserve(self.records(error={"a": 1.}, idle=("b", "c")))
        self.assertEqual(root["frontier"], ["a"])

    def test_missing_source_or_topology_abstains(self):
        records = self.records(error={"a": 1., "b": 1.})
        for options in ({"source_states": {"a": "available", "b": "unavailable", "c": "available"}},
                        {"edges": []}, {"edges": self.edges + [{"source": "c", "target": "a", "presence": 1.}]}):
            result = self.run_reserve(records, **options)
            self.assertFalse(result["applied"])
            self.assertEqual(result["ranking"], self.ranking)

    def test_rename_and_record_order_invariance(self):
        records = self.records(error={"a": 1., "b": 1., "c": 1.})
        expected = self.run_reserve(records)
        names = {"a": "z", "b": "x", "c": "y"}
        actual = self.run_reserve(
            [dict(r, service=names[r["service"]]) for r in reversed(records)],
            ranking=[dict(r, service=names[r["service"]]) for r in self.ranking],
            services=tuple(names.values()),
            healthy={names[s]: v for s, v in fit_healthy(self.records(), self.services).items()},
            source_states=dict.fromkeys(names.values(), "available"),
            edges=[dict(e, source=names[e["source"]], target=names[e["target"]]) for e in self.edges])
        self.assertEqual([names[r["service"]] for r in expected["ranking"]],
                         [r["service"] for r in actual["ranking"]])

    def test_bad_units_and_truth_topology_rejected(self):
        records = self.records(error={"a": 1.})
        records[0]["unit"] = "bytes_per_second"
        with self.assertRaises(ValueError):
            self.run_reserve(records)
        with self.assertRaises(ValueError):
            self.run_reserve(edges=[dict(self.edges[0], root="a")])
        before = copy.deepcopy(self.ranking)
        self.run_reserve(self.records(error={"a": 1., "b": 1.}))
        self.assertEqual(before, self.ranking)


if __name__ == "__main__":
    unittest.main()
