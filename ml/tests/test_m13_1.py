import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from rca_ml.m13_1_nested import ARCHITECTURES, GRID, INNER_FOLDS, OUTER_FOLDS


ROOT = Path(__file__).resolve().parents[2]


class M131NestedValidationTest(unittest.TestCase):
    def test_preregistered_protocol_and_frozen_inputs(self):
        protocol = (ROOT / "docs/m13-1-protocol.md").read_text()
        manifest = json.loads((ROOT / "ml/models/m13-1/frozen-inputs.json").read_text())
        self.assertIn("PRE-REGISTERED BEFORE NESTED SCORING", protocol)
        self.assertEqual(OUTER_FOLDS, manifest["outer_folds"])
        self.assertEqual(INNER_FOLDS, manifest["inner_folds"])
        self.assertEqual(list(ARCHITECTURES), manifest["architectures"])
        self.assertEqual(0, manifest["m12_incidents_used"])
        self.assertFalse(manifest["reserved_final_scored"])
        for relative, expected in manifest["m13_sha256"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative)

    def test_grid_is_exactly_the_frozen_small_search(self):
        actual = {(item["max_depth"], item["eta"], item["rounds"]) for item in GRID}
        expected = {(depth, eta, rounds) for depth in (2, 3) for eta in (.03, .08) for rounds in (24, 48)}
        self.assertEqual(expected, actual)

    def test_nested_artifact_proves_outer_isolation(self):
        path = ROOT / "ml/models/m13-1/evaluation.json"
        if not path.exists():
            self.skipTest("M13.1 evaluation is generated after nested validation")
        evaluation = json.loads(path.read_text())
        self.assertEqual(5, len(evaluation["outer_folds"]))
        test_ids = []
        for fold in evaluation["outer_folds"]:
            self.assertTrue(fold["train_test_clusters_disjoint"])
            self.assertFalse(fold["outer_test_used_for_selection"])
            self.assertEqual(96, fold["train_incidents"])
            self.assertEqual(24, fold["test_incidents"])
            self.assertEqual(48, fold["train_clusters"])
            self.assertEqual(12, fold["test_clusters"])
            self.assertIn(fold["selected_architecture"], ARCHITECTURES)
            self.assertIn(fold["selected_config"], GRID)
            self.assertEqual(fold["outer_train_ids_sha256"], fold["inner_selection_ids_sha256"])
            self.assertEqual(len(GRID), len(fold["config_search"]))
            self.assertEqual(set(ARCHITECTURES), {item["architecture"] for item in fold["architecture_search"]})
            self.assertFalse(fold["final_fit_provenance"]["in_sample_expert_scores_used_for_fusion"])
            self.assertTrue(all(item["train_test_clusters_disjoint"] for item in fold["full_oof_provenance"]))
            for fusion_fold in fold["fusion_oof_provenance"]:
                self.assertEqual(0, fusion_fold["outer_test_incidents_used"])
                self.assertFalse(fusion_fold["in_sample_expert_scores_used_for_fusion"])
                self.assertTrue(all(
                    item["train_test_clusters_disjoint"]
                    for item in fusion_fold["direct_expert_provenance"]
                    + fusion_fold["context_expert_provenance"]
                ))
            test_ids.extend(fold["outer_test_ids"])
        self.assertEqual(120, len(test_ids))
        self.assertTrue(all(value == 1 for value in Counter(test_ids).values()))
        self.assertTrue(all(evaluation["decision_gates"].values()))
        self.assertEqual("YES", evaluation["verdicts"]["final_test_ready"])
        self.assertEqual({
            "m12_incidents_used": 0,
            "re2_re3_incidents_used": 0,
            "reserved_final_incidents_used": 0,
            "reserved_final_scored": False,
        }, evaluation["data_isolation"])

    def test_post_run_integrity(self):
        path = ROOT / "ml/models/m13-1/integrity-manifest.json"
        if not path.exists():
            self.skipTest("M13.1 integrity is generated after nested validation")
        manifest = json.loads(path.read_text())
        for relative, expected in manifest["sha256"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative)


if __name__ == "__main__":
    unittest.main()
