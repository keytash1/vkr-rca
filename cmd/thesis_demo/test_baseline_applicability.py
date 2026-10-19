"""Provenance checks must not become model confidence or an implicit refit."""

import copy
import json
import unittest

from baseline_applicability import assess, context_projection
from assistant_context import assistant_context
from assistant_tools import SnapshotTools
from assistant_privacy import prepare_outbound_aggregates
from evidence_catalog import build_catalog
from test_evidence_catalog import fixture


def provenance(**changes):
    return {"healthy_start_unix": 10, "healthy_end_unix": 90,
            "workload_reference": {"version": 1, "requests_per_second": 5,
                                   "source": "measured_interval_mean"}} | changes


class ApplicabilityTests(unittest.TestCase):
    def test_same_load_is_only_reference_not_confidence(self):
        value = assess(provenance(), 100, 110, 5, "measured_interval_mean")
        self.assertEqual(value["state"], "REFERENCE_ONLY")
        self.assertEqual(value["temporal_relation"], "PRECEDES")
        self.assertEqual(value["load_relation"], "SAME_REFERENCE_RPS")
        self.assertEqual(value["rps_ratio"], 1)
        self.assertNotIn("confidence", value)
        self.assertEqual(value["reasons"], [])

    def test_load_shift_and_constant_are_not_implicitly_accepted(self):
        value = assess(provenance(), 100, 110, 50, "profile_constant")
        self.assertEqual(value["state"], "REVIEW_REQUIRED")
        self.assertEqual(value["rps_ratio"], 10)
        self.assertIn("LOAD_DIFFERS_FROM_SINGLE_REFERENCE", value["reasons"])
        self.assertIn("CURRENT_LOAD_CONFIGURED_NOT_MEASURED", value["reasons"])
        configured = provenance(workload_reference={"version": 1, "requests_per_second": 5, "source": "profile_constant"})
        self.assertIn("REFERENCE_LOAD_CONFIGURED_NOT_MEASURED", assess(configured, 100, 110, 5)["reasons"])

    def test_future_overlapping_and_missing_periods_are_distinct(self):
        for beginning, ending, state in [(111, 120, "AFTER"), (95, 105, "OVERLAPS"),
                                         (10, 99, "PRECEDES"), (10, 100, "OVERLAPS"),
                                         (110, 120, "OVERLAPS")]:
            value = assess(provenance(healthy_start_unix=beginning, healthy_end_unix=ending), 100, 110, 5, "measured_interval_mean")
            self.assertEqual(value["temporal_relation"], state)
        for old in ({}, {"healthy_end_unix": 90}, {"healthy_start_unix": True, "healthy_end_unix": 90}):
            value = assess(old, 100, 110, 5)
            self.assertEqual(value["temporal_relation"], "UNKNOWN")
            self.assertIsNone(value["reference_rps"])
            self.assertEqual(value["state"], "REVIEW_REQUIRED")

    def test_malformed_metadata_stays_unknown_and_json_finite(self):
        for bad in [None, True, [], {}, float("nan"), float("inf"), -1, 0, "5", 10**1000]:
            value = assess(provenance(workload_reference={"version": 1, "requests_per_second": bad, "source": []}), 100, 110, 5, {})
            self.assertIsNone(value["reference_rps"])
            json.dumps(value, allow_nan=False)
        extreme = assess(provenance(workload_reference={"version": 1, "requests_per_second": 1e-300, "source": "measured_interval_mean"}), 100, 110, 1e300)
        self.assertIsNone(extreme["rps_ratio"])
        json.dumps(extreme, allow_nan=False)

    def test_catalog_facts_and_source_inputs_remain_identical(self):
        window, result, baseline = fixture()
        old = copy.deepcopy((window, result, baseline))
        first = build_catalog(window, result, baseline)
        second = build_catalog(window, result, baseline, baseline_provenance=provenance(), source_status={"workload_source": "measured_interval_mean"})
        # Healthy period is part of existing fact identity; compare with the same
        # period and only the new explanatory metadata removed.
        prior = provenance(); prior.pop("workload_reference")
        third = build_catalog(window, result, baseline, baseline_provenance=prior, source_status={"workload_source": "measured_interval_mean"})
        self.assertEqual(second["observations"], third["observations"])
        self.assertEqual((window, result, baseline), old)
        self.assertEqual(first["input_sha256"], second["input_sha256"])

    def test_blind_llm_gets_the_same_allowlisted_explanation_without_poison(self):
        catalog = build_catalog(*fixture(), baseline_provenance=provenance(), source_status={"workload_source": "measured_interval_mean"})
        value = catalog["source_quality"]["baseline_applicability"]
        clean = assistant_context(catalog)
        self.assertEqual(clean["source_quality"]["baseline_applicability"], value)
        self.assertEqual(SnapshotTools(catalog).initial_context()["source_quality"], clean["source_quality"])
        outbound, _, _ = prepare_outbound_aggregates(catalog)
        self.assertEqual(outbound["source_quality"]["baseline_applicability"], value)
        value.update(secret="POISON", ranking_hint="POISON", reasons=["POISON"], state="POISON", rps_ratio="POISON")
        value["reference_source"] = {"token": "POISON"}
        projected = context_projection(value, 100, 110, 5)
        self.assertNotIn("POISON", json.dumps(projected))
        self.assertIsNone(projected["reference_rps"])
        outbound, _, _ = prepare_outbound_aggregates(catalog)
        self.assertNotIn("POISON", json.dumps(outbound))


if __name__ == "__main__":
    unittest.main()
