import copy
import unittest
from rca_ml.r3_dependency_overlap import summarize_overlap, overlap_features


def span(identifier, service, parent="", start=0, duration=100, trace="t"):
    return dict(trace_id=trace, span_id=identifier, parent_span_id=parent,
                service=service, start_time_us=start, duration_us=duration, span_kind="UNKNOWN")


class OverlapContract(unittest.TestCase):
    def test_union_not_sum_and_local_descendant_frontier(self):
        x = [span("a", "a"), span("local", "a", "a"),
             span("b", "b", "local", 10, 60), span("c", "c", "a", 50, 40),
             span("deeper", "d", "b", 15, 90)]
        r = summarize_overlap(x, ["a", "b", "c", "d"], 0, 100)
        self.assertEqual(r["a"]["entries"], 1)
        self.assertEqual(r["a"]["overlap_median"], .8)
        self.assertEqual(r["a"]["residual_median"], 20)

    def test_role_order_and_rename_invariance(self):
        x = [span("a", "a"), span("b", "b", "a", 10, 60)]
        a = summarize_overlap(x, ["a", "b"], 0, 100)
        y = copy.deepcopy(list(reversed(x)))
        for p in y:
            p["service"] = {"a": "z", "b": "q"}[p["service"]]
            p["span_kind"] = "CLIENT"
        b = summarize_overlap(y, ["q", "z"], 0, 100)
        self.assertEqual(a["a"], b["z"])
        self.assertEqual(a["b"], b["q"])

    def test_async_clipping_and_missing_parent(self):
        r = summarize_overlap([span("a", "a", "missing"), span("b", "b", "a", 50, 200)], ["a"], 0, 100)["a"]
        self.assertEqual(r["overlap_median"], .5)
        self.assertEqual(r["missing_parent"], 1)
        self.assertEqual(r["clipped_boundaries"], 1)

    def test_trace_scoping_and_outside_window(self):
        x = [span("a", "a"), span("a", "b", trace="other"), span("out", "a", start=200)]
        r = summarize_overlap(x, ["a", "b"], 0, 100)
        self.assertEqual(r["a"]["entries"], 1)
        self.assertEqual(r["a"]["overlap_median"], 0)

    def test_reject_corruption_and_truth(self):
        for x in ([span("a", "a"), span("a", "b")],
                  [span("a", "a", "b"), span("b", "b", "a")],
                  [dict(span("a", "a"), root_service="a")],
                  [span("a", "a", duration=-1)], [span("a", "a", start=float("nan"))]):
            with self.assertRaises(ValueError):
                summarize_overlap(x, ["a", "b"], 0, 100)

    def test_absence_and_healthy_comparison(self):
        a = summarize_overlap([span("a", "a")], ["a", "b"], 0, 100)
        b = summarize_overlap([], ["a", "b"], 0, 100)
        f = overlap_features(b, a)
        self.assertEqual(f["a"]["dep_entry_observed"], 0)
        self.assertEqual(f["a"]["dep_residual_median_log_ratio"], 0)
        self.assertEqual(overlap_features(a, a)["a"]["dep_overlap_median_shift"], 0)


if __name__ == "__main__":
    unittest.main()
