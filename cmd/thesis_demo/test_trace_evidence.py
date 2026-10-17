import unittest
from unittest.mock import patch

from trace_evidence import quantile, summarize_timings


def span(identifier, *, service="alpha", parent="", start=1_000_000, duration=100_000, kind="SERVER"):
    return {"trace_id": "one", "span_id": identifier, "service": service, "parent_span_id": parent,
            "start_time_us": start, "duration_us": duration, "span_kind": kind}


class TimingTests(unittest.TestCase):
    def test_overlap_is_union_not_sum_and_other_service_not_subtracted_twice(self):
        spans = [span("root"), span("client", parent="root", start=1_020_000, duration=60_000, kind="CLIENT"),
                 span("nested", parent="client", start=1_040_000, duration=50_000, kind="CLIENT"),
                 span("server-b", service="beta", parent="client", start=1_020_000, duration=60_000)]
        result = summarize_timings(spans, ["alpha", "beta"], 1_000_000, 1_100_000)
        self.assertEqual(result["alpha"]["median_us"], 100_000)
        self.assertEqual(result["alpha"]["observed_client_wait_median_us"], 70_000)
        self.assertEqual(result["alpha"]["observed_exclusive_median_us"], 30_000)
        self.assertEqual(result["beta"]["observed_exclusive_median_us"], 60_000)

    def test_overhang_context_clipped_to_selected_parent(self):
        spans = [span("root"), span("client", parent="root", start=1_050_000, duration=100_000, kind="CLIENT")]
        result = summarize_timings(spans, ["alpha"], 1_000_000, 1_010_000)["alpha"]
        self.assertEqual(result["timed_spans"], 1)
        self.assertEqual(result["observed_client_wait_median_us"], 50_000)

    def test_unknown_kind_and_missing_spans_are_not_zero_processing_time(self):
        result = summarize_timings([span("root", kind="UNKNOWN", parent="missing")], ["alpha", "beta"], 0, 2_000_000)
        self.assertEqual(result["alpha"]["selection"], "ALL_KINDS_NO_SERVER_OBSERVED")
        self.assertIsNone(result["alpha"]["observed_exclusive_median_us"])
        self.assertEqual(result["alpha"]["unresolved_parent_spans"], 1)
        self.assertIsNone(result["beta"]["median_us"])
        self.assertEqual(result["beta"]["timed_spans"], 0)

    def test_work_budget_and_cycle_fail_safely(self):
        with patch("trace_evidence.MAX_VISITS", 0):
            value = summarize_timings([span("root"),span("child",parent="root",kind="CLIENT")], ["alpha"], 0, 2_000_000)["alpha"]
        self.assertEqual(value["wait_state"], "BUDGET_EXCEEDED")
        self.assertIsNone(value["observed_exclusive_median_us"])
        with self.assertRaises(ValueError):
            summarize_timings([span("root",parent="root")], ["alpha"], 0, 2_000_000)

    def test_quantile_is_explicit_linear_interpolation(self):
        self.assertEqual(quantile([10,20],.9),19)
        self.assertIsNone(quantile([], .5))


if __name__ == "__main__": unittest.main()
