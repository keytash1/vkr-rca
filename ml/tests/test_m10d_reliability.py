import copy
import math
import unittest

import numpy as np

from rca_ml.m10d_reliability import (
    FEATURE_COLUMNS, FORBIDDEN_FEATURE_TOKENS, SEEDS, bootstrap_accuracy_delta,
    calibration_metrics, deterministic_split, ensure_truth_free_inference,
    evaluate_policy, fit_isotonic, fit_logistic, fit_ood_bounds, fit_policy,
    fit_regime_boundaries, policy_accepts, predict_method, regime,
    risk_coverage,
)


def record(index, correct, margin=None):
    values = {name: 0.5 for name in FEATURE_COLUMNS}
    values.update({
        "margin_top1_top2": float(index / 20 if margin is None else margin),
        "margin_top1_top3": float(index / 18),
        "normalized_rank_gap": float(index / 22),
        "inverse_candidate_count": 0.2,
        "incident_ood": 0.0,
        "expert_agreement": 0.8,
        "metrics_present": 1.0,
        "traces_present": 1.0,
        "topology_present": 1.0,
    })
    return {"incident_id": f"opaque-{index}", "top1_service": "not-a-feature",
            "candidate_count": 5, "conformal_set_size_90": 2,
            "features": values, "top1_correct": bool(correct),
            "truth_rank": 1 if correct else 2}


class M10DReliabilityTests(unittest.TestCase):
    def test_split_is_deterministic_disjoint_and_identity_opaque(self):
        ids = [f"case-{i}" for i in range(50)]
        first = deterministic_split(ids, "unit")
        second = deterministic_split(list(reversed(ids)), "unit")
        self.assertEqual(first, second)
        self.assertFalse(set(first[0]) & set(first[1]))
        self.assertEqual(set(ids), set(first[0]) | set(first[1]))

    def test_reliability_feature_schema_has_no_identity(self):
        for name in FEATURE_COLUMNS:
            self.assertFalse(any(token in name for token in FORBIDDEN_FEATURE_TOKENS), name)
        self.assertEqual(len(SEEDS), 5)

    def test_ood_fit_ignores_test_rows_and_labels(self):
        columns = __import__("rca_ml.m10c_schema", fromlist=["FEATURE_COLUMNS_M10C"]).FEATURE_COLUMNS_M10C
        rows = []
        for incident, value in (("train-a", 0.0), ("train-b", 1.0), ("test", 1_000_000.0)):
            row = {name: value for name in columns}
            row.update({"incident_id": incident, "service": "svc", "label": int(incident == "test")})
            rows.append(row)
        before = fit_ood_bounds(rows, ["train-a", "train-b"])
        rows[-1].update({name: -1_000_000.0 for name in columns})
        rows[-1]["label"] = 0
        after = fit_ood_bounds(rows, ["train-a", "train-b"])
        self.assertEqual(before, after)

    def test_risk_coverage_and_abstention_are_correct(self):
        records = [record(4, True), record(3, True), record(2, False), record(1, False)]
        scores = [0.9, 0.8, 0.2, 0.1]
        policy = {"method": "margin", "threshold": 0.8}
        result = evaluate_policy(records, scores, policy)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["selective_ac_at_1"], 1.0)
        self.assertEqual(result["selective_mrr"], 1.0)
        self.assertGreaterEqual(risk_coverage(records, scores)["aurc"], 0.0)

    def test_isotonic_and_logistic_are_deterministic(self):
        records = [record(i, i >= 7) for i in range(1, 15)]
        matrix = np.asarray([[item["features"][name] for name in FEATURE_COLUMNS] for item in records])
        iso_a, iso_b = fit_isotonic(records), fit_isotonic(copy.deepcopy(records))
        np.testing.assert_allclose(iso_a.predict(matrix), iso_b.predict(matrix))
        self.assertTrue(np.all(np.diff(iso_a.predict(matrix)) >= -1e-12))
        log_a, log_b = fit_logistic(records, iterations=100), fit_logistic(copy.deepcopy(records), iterations=100)
        np.testing.assert_allclose(log_a.predict(matrix), log_b.predict(matrix))

    def test_mondrian_boundaries_use_only_allowed_numeric_signals(self):
        records = [record(i, i % 2 == 0) for i in range(1, 30)]
        first = fit_regime_boundaries(records)
        changed = copy.deepcopy(records)
        for item in changed:
            item.update({"system": "forbidden", "dataset": "forbidden", "fault": "forbidden", "root": "forbidden"})
        self.assertEqual(first, fit_regime_boundaries(changed))
        self.assertNotIn("forbidden", regime(changed[0], first))

    def test_threshold_is_not_changed_by_test_evaluation(self):
        calibration = [record(i, i >= 5) for i in range(1, 11)]
        policy = fit_policy("margin", None, calibration, 0.9)
        frozen = copy.deepcopy(policy)
        test = [record(100 + i, False, margin=1.0) for i in range(10)]
        evaluate_policy(test, predict_method("margin", None, test), policy)
        self.assertEqual(policy, frozen)

    def test_infeasible_policy_uses_json_safe_null_and_abstains(self):
        calibration = [record(i, False) for i in range(1, 11)]
        policy = fit_policy("margin", None, calibration, 0.9)
        self.assertIsNone(policy["threshold"])
        self.assertFalse(policy_accepts(policy, calibration[0], 1.0))

    def test_truth_is_removed_from_inference_record(self):
        value = ensure_truth_free_inference(record(1, True))
        self.assertNotIn("top1_correct", value)
        self.assertNotIn("truth_rank", value)
        self.assertIn("features", value)

    def test_calibration_metrics_and_bootstrap_are_finite(self):
        records = [record(i, i % 3 != 0) for i in range(1, 31)]
        probabilities = np.linspace(0.1, 0.9, len(records))
        result = calibration_metrics(records, probabilities)
        self.assertTrue(0 <= result["brier"] <= 1)
        self.assertTrue(0 <= result["ece"] <= 1)
        paired = bootstrap_accuracy_delta(records, probabilities, probabilities[::-1], 0.5, resamples=100, seed=20260906)
        self.assertTrue(math.isfinite(paired["difference"]))
        self.assertEqual(paired["seed"], 20260906)

    def test_mondrian_policy_falls_back_to_global_threshold(self):
        item = record(1, True)
        policy = {"method": "mondrian", "threshold": 0.7,
                  "regime_boundaries": fit_regime_boundaries([item]), "regime_thresholds": {}}
        self.assertTrue(policy_accepts(policy, item, 0.8))
        self.assertFalse(policy_accepts(policy, item, 0.6))


if __name__ == "__main__":
    unittest.main()
