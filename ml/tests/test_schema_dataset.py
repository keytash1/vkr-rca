from __future__ import annotations

import copy
import math
import unittest

from rca_ml.dataset import build_candidate_rows, feature_rows, validate_candidate_rows
from rca_ml.fixtures import fixture_dataset
from rca_ml.schema import FEATURE_COLUMNS, FORBIDDEN_FEATURE_COLUMNS, validate_schema
from rca_ml.split import duplicate_fingerprints_across_splits, stratified_split


class SchemaDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.features, self.labels = fixture_dataset()
        self.assignments = stratified_split(self.labels, seed=42)
        self.rows = build_candidate_rows(self.features, self.labels, self.assignments)

    def test_feature_whitelist_has_no_forbidden_fields(self) -> None:
        validate_schema()
        self.assertFalse(set(FEATURE_COLUMNS) & FORBIDDEN_FEATURE_COLUMNS)
        self.assertNotIn("service", FEATURE_COLUMNS)

    def test_numeric_matrix_is_finite(self) -> None:
        self.assertTrue(self.rows)
        for row in self.rows:
            self.assertTrue(all(math.isfinite(float(row[column])) for column in FEATURE_COLUMNS))

    def test_one_positive_per_group_and_contiguous(self) -> None:
        validate_candidate_rows(self.rows, {label["incident_id"]: label for label in self.labels})
        incident_ids = [row["incident_id"] for row in self.rows]
        self.assertEqual(incident_ids, sorted(incident_ids))

    def test_validation_rejects_interleaved_group(self) -> None:
        first = [row for row in self.rows if row["incident_id"] == self.rows[0]["incident_id"]]
        second_id = next(row["incident_id"] for row in self.rows if row["incident_id"] != first[0]["incident_id"])
        second = [row for row in self.rows if row["incident_id"] == second_id]
        broken = [first[0], *second, *first[1:]]
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_candidate_rows(broken)

    def test_validation_rejects_zero_positive(self) -> None:
        broken = copy.deepcopy(self.rows[:3])
        for row in broken:
            row["label"] = 0
        with self.assertRaisesRegex(ValueError, "0 positives"):
            validate_candidate_rows(broken)

    def test_incident_split_is_deterministic_and_never_crosses(self) -> None:
        self.assertEqual(self.assignments, stratified_split(self.labels, seed=42))
        by_incident = {}
        for row in self.rows:
            by_incident.setdefault(row["incident_id"], set()).add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in by_incident.values()))
        qid_to_incident = {}
        for row in self.rows:
            self.assertEqual(qid_to_incident.setdefault(row["qid"], row["incident_id"]), row["incident_id"])

    def test_duplicate_scenario_fingerprint_detection(self) -> None:
        labels = copy.deepcopy(self.labels)
        incident_a = next(key for key, value in self.assignments.items() if value == "train")
        incident_b = next(key for key, value in self.assignments.items() if value == "test")
        by_id = {label["incident_id"]: label for label in labels}
        by_id[incident_b]["scenario_fingerprint"] = by_id[incident_a]["scenario_fingerprint"]
        self.assertEqual(len(duplicate_fingerprints_across_splits(labels, self.assignments)), 1)

    def test_feature_builder_is_deterministic(self) -> None:
        snapshot = self.features[0]["feature_snapshot"]
        self.assertEqual(feature_rows(snapshot), feature_rows(copy.deepcopy(snapshot)))

    def test_service_rename_does_not_change_numeric_vectors(self) -> None:
        original = self.features[0]["feature_snapshot"]
        renamed = copy.deepcopy(original)
        mapping = {"gateway": "zeta", "orders": "alpha", "payment": "mu"}
        renamed["ready_universe"] = [mapping[value] for value in renamed["ready_universe"]]
        renamed["observed_anomalies"] = [mapping[value] for value in renamed["observed_anomalies"]]
        for edge in renamed["topology_edges"]:
            edge["caller"] = mapping[edge["caller"]]
            edge["callee"] = mapping[edge["callee"]]
        for service in renamed["services"]:
            service["service"] = mapping[service["service"]]
            service["expected_affected_services"] = [mapping[value] for value in service["expected_affected_services"]]
        original_vectors = sorted(tuple(values[column] for column in FEATURE_COLUMNS) for _, values in feature_rows(original))
        renamed_vectors = sorted(tuple(values[column] for column in FEATURE_COLUMNS) for _, values in feature_rows(renamed))
        self.assertEqual(original_vectors, renamed_vectors)


if __name__ == "__main__":
    unittest.main()
