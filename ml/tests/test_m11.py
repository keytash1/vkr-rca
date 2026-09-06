import json
import unittest
from pathlib import Path

import xgboost as xgb

from rca_ml.dataset import sha256_file
from rca_ml.m10d_reranker import RERANKER_FEATURES, SEEDS
from rca_ml.m11_protocol import (
    assert_selection_ids_allowed,
    assert_truth_free_adapter_output,
    cluster_bootstrap,
    ranking_metrics,
    rerank_top_k,
    transition_locked_test,
)


ROOT = Path(__file__).resolve().parents[2]
M11 = ROOT / "ml/models/m11"


def _ranking(root_rank=2):
    return [
        {"service": name, "rank": rank, "score": 1.0 / rank, "label": int(rank == root_rank)}
        for rank, name in enumerate(("a", "b", "c", "d", "e"), 1)
    ]


class M11ProtocolTests(unittest.TestCase):
    def test_used_and_locked_test_ids_are_excluded(self):
        datasets = {"dev-1": "RE1-OB", "used-1": "RE2-OB", "locked-1": "NEW-LOCKED"}
        roles = {
            "RE1-OB": "DEVELOPMENT_EXISTING",
            "RE2-OB": "USED_TEST_READONLY",
            "NEW-LOCKED": "LOCKED_NEW_TEST",
        }
        assert_selection_ids_allowed(["dev-1"], datasets, roles)
        with self.assertRaisesRegex(ValueError, "used/locked test"):
            assert_selection_ids_allowed(["dev-1", "used-1"], datasets, roles)
        with self.assertRaisesRegex(ValueError, "used/locked test"):
            assert_selection_ids_allowed(["locked-1"], datasets, roles)

    def test_truth_and_identity_are_isolated_from_adapter_output(self):
        assert_truth_free_adapter_output([{"incident_id": "x", "service": "a", "value": 1.0}])
        for key in ("label", "root_service", "fault_type", "dataset", "system"):
            with self.assertRaisesRegex(ValueError, "truth or semantic identity"):
                assert_truth_free_adapter_output([{"incident_id": "x", "service": "a", key: "leak"}])

    def test_locked_test_transition_is_one_time_and_irreversible(self):
        ledger = {
            "roles": {"new-test": "LOCKED_NEW_TEST"},
            "locked_test_transition": {"transitions": []},
        }
        opened = transition_locked_test(ledger, "new-test")
        self.assertEqual(opened["roles"]["new-test"], "USED_TEST")
        self.assertEqual(ledger["roles"]["new-test"], "LOCKED_NEW_TEST")
        with self.assertRaisesRegex(ValueError, "not in LOCKED_NEW_TEST"):
            transition_locked_test(opened, "new-test")

    def test_top_k_membership_and_tail_order_are_preserved(self):
        rankings = {"i": _ranking()}
        predictions = {("i", name): score for name, score in (("a", .1), ("b", .8), ("c", .9))}
        result = rerank_top_k(rankings, predictions, 3)["i"]
        self.assertEqual({item["service"] for item in result[:3]}, {"a", "b", "c"})
        self.assertEqual([item["service"] for item in result[3:]], ["d", "e"])
        self.assertEqual([item["service"] for item in result[:3]], ["c", "b", "a"])

    def test_denominator_keeps_unobservable_roots(self):
        rankings = {"hit": _ranking(1), "missing": [{**item, "label": 0} for item in _ranking(1)]}
        metrics = ranking_metrics(rankings)
        self.assertEqual(metrics["incidents"], 2)
        self.assertEqual(metrics["root_observable"], 1)
        self.assertEqual(metrics["candidate_universe_coverage"], .5)
        self.assertEqual(metrics["ac_at_1"], .5)

    def test_cluster_bootstrap_is_deterministic_and_clustered_by_root(self):
        baseline = {"i1": _ranking(2), "i2": _ranking(2), "i3": _ranking(1)}
        challenger = {"i1": _ranking(1), "i2": _ranking(1), "i3": _ranking(1)}
        cases = {
            "i1": {"system": "s1", "root": "r1", "fault": "cpu"},
            "i2": {"system": "s1", "root": "r1", "fault": "cpu"},
            "i3": {"system": "s2", "root": "r2", "fault": "network"},
        }
        first = cluster_bootstrap(challenger, baseline, cases, metric="ac_at_1", resamples=200)
        second = cluster_bootstrap(challenger, baseline, cases, metric="ac_at_1", resamples=200)
        self.assertEqual(first, second)
        self.assertEqual(first["clusters"], 2)
        self.assertEqual(first["seed"], 20260906)

    def test_preflight_hashes_and_seeds_are_exact(self):
        preflight = json.loads((M11 / "preflight.json").read_text())
        self.assertEqual(preflight["base_commit"], "2fd38885ef8c0f0930d1830d8fd429fb6594f8a4")
        self.assertEqual(tuple(preflight["candidate_recovery"]["model_seeds"]), SEEDS)
        self.assertEqual(preflight["bootstrap"], {
            "cluster_key": ["system", "root_service", "fault_type"],
            "resamples": 10000,
            "seed": 20260906,
        })
        for relative, expected in preflight["sha256"].items():
            self.assertEqual(sha256_file(ROOT / relative), expected, relative)

    def test_feature_schema_has_no_identity_or_truth(self):
        self.assertEqual(len(RERANKER_FEATURES), 13)
        for name in ("service", "system", "dataset", "label", "root_service", "fault_type"):
            self.assertNotIn(name, RERANKER_FEATURES)

    def test_oof_folds_are_group_disjoint_when_evaluation_exists(self):
        evaluation_path = M11 / "evaluation.json"
        if not evaluation_path.exists():
            self.skipTest("run m11-experiment first")
        evaluation = json.loads(evaluation_path.read_text())
        for variant in evaluation["candidate_recovery"]["variants"].values():
            for fold in variant["oof_provenance"]["folds"]:
                self.assertTrue(fold["incident_ids_disjoint"])
                self.assertNotIn(fold["held_out"], fold["train_datasets"])
                self.assertEqual(fold["used_test_cases"], 0)

    def test_final_artifact_schema_and_frozen_historical_metrics(self):
        evaluation_path = M11 / "evaluation.json"
        if not evaluation_path.exists():
            self.skipTest("run m11-experiment first")
        evaluation = json.loads(evaluation_path.read_text())
        self.assertEqual(evaluation["version"], "m11-generalization-hardening-v1")
        self.assertTrue(evaluation["protocol_order"]["freeze_manifest_written_before_historical_access"])
        metrics = evaluation["historical_post_freeze"]["frozen_m10d_baseline"]["metrics"]
        self.assertAlmostEqual(metrics["ac_at_1"], .8361111111111111)
        self.assertAlmostEqual(metrics["ac_at_2"], .9305555555555556)
        self.assertAlmostEqual(metrics["ac_at_3"], .9416666666666667)
        self.assertAlmostEqual(metrics["mrr"], .8977211099086099)

    def test_selected_five_seed_models_are_reproducible_and_integral(self):
        freeze_path = M11 / "freeze-manifest.json"
        if not freeze_path.exists():
            self.skipTest("run m11-experiment first")
        freeze = json.loads(freeze_path.read_text())
        self.assertEqual(tuple(freeze["model_seeds"]), SEEDS)
        self.assertEqual(len(freeze["models"]), 5)
        for relative, expected in freeze["models"].items():
            path = ROOT / relative
            self.assertEqual(sha256_file(path), expected)
            model = xgb.Booster()
            model.load_model(path)
            self.assertEqual(tuple(model.feature_names or ()), RERANKER_FEATURES)

        evaluation = json.loads((M11 / "evaluation.json").read_text())
        selected_k = str(evaluation["candidate_recovery"]["selected"]["top_k"])
        robustness = evaluation["candidate_recovery"]["variants"][selected_k]["oof_provenance"]["five_seed_robustness"]
        self.assertEqual(set(robustness), {str(seed) for seed in SEEDS})


if __name__ == "__main__":
    unittest.main()
