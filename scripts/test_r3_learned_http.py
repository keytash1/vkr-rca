"""Bounded C2 input checks, no collection/model fitting/provider calls."""
from copy import deepcopy
import unittest
import numpy as np

from rca_ml import r3_metric_contract as c
from r3_learned_http import planned_cases, matrix, predict, red_ranking, mask_cpu
from test_r3_metric_contract import period


def frame():
    return c.extract(c.fit_reference(period()), period(2000))


class LearnedHTTPContract(unittest.TestCase):
    def test_predeclared_balanced_case_plan(self):
        cases = planned_cases()
        self.assertEqual(cases, planned_cases())
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({r["id"] for r in cases}), 12)
        for service in ("gateway", "orders", "payment"):
            self.assertEqual(sum(r["service"] == service for r in cases), 4)

    def test_changed_schema_or_semantics_rejected(self):
        for key in ("columns", "schema_sha256", "semantic_sha256"):
            payload = frame(); payload[key] = "old-cache"
            with self.assertRaises(ValueError):
                matrix(payload)

    def test_numeric_predictions_have_no_targets(self):
        class Stub:
            def predict(self, data):
                self.seen_labels = data.get_label()
                return np.asarray([.25])
        model = Stub()
        payload = frame()
        output = predict(model, payload)
        self.assertEqual(output, [dict(service="a", score=.25, rank=1)])
        self.assertEqual(model.seen_labels.size, 0)
        # Row metadata never becomes an extra model input.
        payload["rows"][0]["root_cause"] = "irrelevant"
        self.assertEqual(output, predict(model, payload))

    def test_missing_cpu_preserves_inventory_and_other_families(self):
        original = period(2000)
        masked = mask_cpu(original)
        self.assertEqual(original.services, masked.services)
        self.assertEqual(len(original.records), len(masked.records))
        self.assertEqual([r for r in original.records if r[1] != "cpu"],
                         [r for r in masked.records if r[1] != "cpu"])
        self.assertTrue(all(r[3:] == ("MISSING", None) for r in masked.records if r[1] == "cpu"))

    def test_red_comparator_uses_only_declared_http_shifts(self):
        original = frame()
        altered = deepcopy(original)
        altered["rows"][0]["vector"][c.COLUMNS.index("cpu_signed_median_shift")] = 1e6
        self.assertEqual(red_ranking(original), red_ranking(altered))

    def test_duplicate_or_nonfinite_candidates_rejected(self):
        payload = frame(); payload["rows"] *= 2
        with self.assertRaises(ValueError):
            matrix(payload)
        payload = frame(); payload["rows"][0]["vector"][0] = float("nan")
        with self.assertRaises(ValueError):
            matrix(payload)


if __name__ == "__main__":
    unittest.main()
