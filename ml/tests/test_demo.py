import json
import unittest
from pathlib import Path

from rca_ml.demo_predict import FEATURE_COLUMNS_M9B, canonical_json, human_label, predict_prepared
from rca_ml.demo_prepare import validate_selection, verify_frozen


ROOT = Path(__file__).resolve().parents[2]


class DemoTests(unittest.TestCase):
    def test_frozen_research_manifest_matches_repository(self):
        result = verify_frozen(ROOT)
        self.assertEqual(result["status"], "identical")
        self.assertGreaterEqual(result["files"], 10)

    def test_showcase_selection_is_pinned_and_has_misses(self):
        selection = json.loads((ROOT / "demo/cases.json").read_text())
        validate_selection(selection)
        self.assertEqual(len(selection["cases"]), 8)
        self.assertGreaterEqual(sum(value["expected_actual_rank"] > 1 for value in selection["cases"]), 2)

    def test_prediction_is_unchanged_after_label_metadata_rename(self):
        vectors = []
        for service, cpu in (("alpha", 0.2), ("beta", 4.0)):
            vector = {name: 0.0 for name in FEATURE_COLUMNS_M9B}
            vector["metric_cpu_has"] = 1.0
            vector["metric_cpu_max_shift"] = cpu
            vectors.append({"service": service, "vector": vector})
        prepared = {
            "external_case_id": "truth-blind-fixture",
            "dataset": "RE2-OB",
            "system": "fixture",
            "incident_timestamp": 1,
            "features": {
                "schema_version": "m9b-v1",
                "services": vectors,
                "mapping_coverage": {"entities": 2, "matched": 2},
            },
        }
        label_metadata = {"root_service": "alpha", "fault_family": "cpu"}
        first = canonical_json(predict_prepared(prepared, ROOT))
        label_metadata["root_service"] = "renamed-service"
        label_metadata["fault_family"] = "renamed-fault"
        second = canonical_json(predict_prepared(prepared, ROOT))
        self.assertEqual(first, second)
        self.assertNotIn("root_service", first)
        self.assertNotIn("fault_family", first)

    def test_human_labels_keep_technical_names_separate(self):
        label = human_label("metric_cpu_max_persistence_percentile")
        self.assertIn("CPU", label)
        self.assertNotEqual(label, "metric_cpu_max_persistence_percentile")


if __name__ == "__main__":
    unittest.main()
