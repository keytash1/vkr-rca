import json
import unittest
from pathlib import Path

from rca_ml.dataset import sha256_file
from rca_ml.m10c_integrity import verify_frozen
from rca_ml.m10c_schema import FEATURE_COLUMNS_M10C
from rca_ml import m10d_reranker
from rca_ml.m10d_integration_experiment import EXPECTED_MODEL_HASHES
from rca_ml.m10d_reranker import (
    COMPONENTS,
    RERANKER_FEATURES,
    build_evidence_features,
    build_reranker_records,
    load_frozen_models,
    rerank_top3,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "ml/models/m10d-integration"


def _row(service: str, **values: float) -> dict:
    row = {name: 0.0 for name in FEATURE_COLUMNS_M10C}
    row.update({"incident_id": "incident", "service": service, **values})
    return row


def _ranking() -> list[dict]:
    return [
        {"service": service, "rank": rank, "score": score}
        for rank, (service, score) in enumerate(
            (("a", .9), ("b", .8), ("c", .7), ("d", .6), ("e", .5)), 1
        )
    ]


class M10DIntegrationTests(unittest.TestCase):
    def test_truth_and_identity_leakage_are_rejected(self):
        rows = [_row("a"), _row("b"), _row("c")]
        rows[0]["label"] = 1
        with self.assertRaisesRegex(ValueError, "truth or semantic identity"):
            build_evidence_features(rows, _ranking())

    def test_feature_extraction_exposes_no_verifier_status(self):
        rows = [
            _row("a", coverage_has_metrics=1, metric_cpu_has=1, metric_cpu_persistence=.8),
            _row("b"),
            _row("c"),
            _row("d"),
            _row("e"),
        ]
        profiles = build_evidence_features(rows, _ranking())
        self.assertEqual(len(profiles), 3)
        self.assertFalse(hasattr(m10d_reranker, "status_for"))
        self.assertFalse(hasattr(m10d_reranker, "STATUSES"))
        for profile in profiles:
            self.assertNotIn("status", profile)
            self.assertNotIn("abstain", profile)
            self.assertEqual(tuple(profile["components"]), COMPONENTS)

    def test_exact_13_feature_schema_has_no_identity(self):
        self.assertEqual(len(RERANKER_FEATURES), 13)
        self.assertNotIn("service", RERANKER_FEATURES)
        self.assertNotIn("system", RERANKER_FEATURES)
        self.assertNotIn("dataset", RERANKER_FEATURES)
        profiles = build_evidence_features(
            [_row(name) for name in ("a", "b", "c", "d", "e")], _ranking()
        )
        records = build_reranker_records("incident", profiles, _ranking())
        for record in records:
            self.assertEqual(
                tuple(name for name in record if name in RERANKER_FEATURES),
                RERANKER_FEATURES,
            )

    def test_reranking_is_deterministic_and_preserves_top3_and_tail(self):
        rankings = {"incident": _ranking()}
        predictions = {
            ("incident", "a"): .1,
            ("incident", "b"): .9,
            ("incident", "c"): .5,
        }
        first = rerank_top3(rankings, predictions)
        second = rerank_top3(rankings, predictions)
        self.assertEqual(first, second)
        self.assertEqual(
            {item["service"] for item in first["incident"][:3]}, {"a", "b", "c"}
        )
        self.assertEqual(
            [item["service"] for item in first["incident"][3:]], ["d", "e"]
        )
        self.assertEqual(
            [item["service"] for item in first["incident"][:3]], ["b", "c", "a"]
        )

    def test_five_frozen_model_hashes_and_schema_match(self):
        for name, expected in EXPECTED_MODEL_HASHES.items():
            self.assertEqual(sha256_file(MODEL_DIR / name), expected)
        models = load_frozen_models(MODEL_DIR)
        self.assertEqual(len(models), 5)
        for model in models:
            self.assertEqual(tuple(model.feature_names or ()), RERANKER_FEATURES)

    def test_m10c_and_earlier_frozen_inputs_are_unchanged(self):
        result = verify_frozen(ROOT)
        self.assertTrue(result["ok"], result["mismatches"])
        evaluation = json.loads((MODEL_DIR / "evaluation.json").read_text())
        self.assertTrue(evaluation["integrity"]["m10c"]["ok"])
        self.assertEqual(
            evaluation["integrity"]["m10c"]["selected_model_sha256"],
            "8452b88958d2fa2972cfcc89c8021f9108e08be690fcc20add1292bcfe8caace",
        )

    def test_oof_provenance_is_system_held_out_and_disjoint(self):
        evaluation = json.loads((MODEL_DIR / "evaluation.json").read_text())
        folds = evaluation["development"]["oof_provenance"]["folds"]
        self.assertEqual({fold["held_out"] for fold in folds}, {"RE1-OB", "RE1-SS", "RE1-TT"})
        for fold in folds:
            self.assertTrue(fold["incident_ids_disjoint"])
            self.assertNotIn(fold["held_out"], fold["train_datasets"])
            self.assertEqual(fold["external_cases_used"], 0)

    def test_external_protocol_is_explicit_and_training_free(self):
        protocol = json.loads((MODEL_DIR / "protocol.json").read_text())
        data = protocol["data_protocol"]
        self.assertFalse(data["external_used_for_training"])
        self.assertFalse(data["external_used_for_feature_selection"])
        self.assertFalse(data["external_used_for_hyperparameter_selection"])
        self.assertFalse(data["external_used_for_model_selection"])
        self.assertTrue(data["external_used_for_final_non_degradation_guard"])

    def test_numerical_regression_and_invariants(self):
        evaluation = json.loads((MODEL_DIR / "evaluation.json").read_text())
        self.assertAlmostEqual(evaluation["development"]["base"]["ac_at_1"], .72)
        self.assertAlmostEqual(evaluation["development"]["reranked"]["ac_at_1"], .7813333333333333)
        self.assertAlmostEqual(evaluation["development"]["base"]["mrr"], .8326417261101472)
        self.assertAlmostEqual(evaluation["development"]["reranked"]["mrr"], .865530614999036)
        self.assertAlmostEqual(evaluation["external_post_freeze"]["base"]["ac_at_1"], .7888888888888889)
        self.assertAlmostEqual(evaluation["external_post_freeze"]["reranked"]["ac_at_1"], .8361111111111111)
        self.assertAlmostEqual(evaluation["external_post_freeze"]["base"]["mrr"], .8690174062049062)
        self.assertAlmostEqual(evaluation["external_post_freeze"]["reranked"]["mrr"], .8977211099086099)
        for scope in ("development", "external"):
            self.assertTrue(evaluation["invariants"][scope]["top3_membership_equal"])
            self.assertTrue(evaluation["invariants"][scope]["tail_relative_order_identical"])

    def test_ablation_is_interpretability_only_and_evidence_drives_gain(self):
        evaluation = json.loads((MODEL_DIR / "evaluation.json").read_text())
        variants = evaluation["ablation"]["variants"]
        self.assertIn("not model reselection", evaluation["ablation"]["scope"])
        self.assertEqual(variants["ranking_context_only"]["metrics"]["ac_at_1"], .72)
        self.assertGreater(
            variants["diagnostic_evidence_only"]["metrics"]["ac_at_1"], .77
        )
        self.assertEqual(
            variants["full_evidence_aware"]["metrics"], evaluation["development"]["reranked"]
        )


if __name__ == "__main__":
    unittest.main()
