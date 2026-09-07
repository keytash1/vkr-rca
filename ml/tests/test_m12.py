import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rca_ml.m11_protocol import rerank_top_k
from rca_ml.m12_adapter import CANONICAL_UNITS, assert_truth_free, canonical_features, robust_baseline
from rca_ml.m12_evaluate import paired_bootstrap, rank_candidates, wilson

ROOT = Path(__file__).resolve().parents[2]


def samples(offset=0.0):
    return [
        {"timestamp": tick, "service": service, "family": family, "value": 1.0 + offset, "unit": unit}
        for tick in range(10) for service in ("a", "b", "c", "d", "e") for family, unit in CANONICAL_UNITS.items()
    ]


class M12ProtocolTest(unittest.TestCase):
    def test_unseen_system_and_locked_design(self):
        system = json.loads((ROOT / "ml/models/m12/system-manifest.json").read_text())
        self.assertNotIn(system["name"].lower(), {"online boutique", "sock shop", "train ticket"})
        self.assertFalse(system["rcaeval_overlap"])
        plan = json.loads((ROOT / "ml/models/m12/incident-plan.json").read_text())
        self.assertEqual(50, len(plan["incidents"]))
        self.assertEqual(25, len({(i["root_service"], i["fault_family"]) for i in plan["incidents"]}))

    def test_role_isolation_and_one_way_policy(self):
        ledger = json.loads((ROOT / "ml/models/m12/data-ledger.json").read_text())
        self.assertIn("M12_LOCKED_TEST", ledger["forbidden_for_training_or_selection"])
        self.assertEqual(1, ledger["locked_transition"]["maximum_transitions"])
        self.assertFalse(ledger["locked_transition"]["reversible"])
        transitions = ledger["locked_transition"]["transitions"]
        self.assertLessEqual(len(transitions), 1)
        self.assertEqual("USED_TEST" if transitions else "M12_LOCKED_TEST", ledger["m12_roles"]["locked"])

    def test_canary_validity_is_prediction_independent(self):
        canary = ROOT / "external-data/m12/runs/locked-v1/canary/validity.json"
        if not canary.exists():
            self.skipTest("external canary evidence is intentionally not versioned")
        evidence = json.loads(canary.read_text())
        self.assertFalse(evidence["rankings_generated"])
        self.assertTrue(all(item["valid"] for item in evidence["results"]))

    def test_truth_and_semantic_identity_rejected(self):
        for key in ("root_service", "fault", "fault_type", "system", "dataset", "label"):
            with self.assertRaises(ValueError):
                assert_truth_free([{"service": "a", key: "secret"}])

    def test_adapter_is_deterministic_and_units_are_strict(self):
        baseline = robust_baseline(samples())
        one = canonical_features(samples(2), baseline, ["a", "b", "c", "d", "e"], [{"source": "a", "target": "b"}])
        two = canonical_features(samples(2), baseline, ["e", "d", "c", "b", "a"], [{"source": "a", "target": "b"}])
        self.assertEqual(one, two)
        bad = samples(); bad[0]["unit"] = "percent"
        with self.assertRaises(ValueError): robust_baseline(bad)

    def test_model_and_schema_hashes_exact(self):
        preflight = json.loads((ROOT / "ml/models/m12/preflight.json").read_text())
        for name, expected in preflight["sha256"].items():
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            self.assertEqual(expected, actual, name)
        schema = json.loads((ROOT / "ml/models/m10c-v2/feature-schema.json").read_text())
        self.assertEqual(32, len(schema["selected_columns"]))
        self.assertEqual(13, len(preflight["feature_schema"]))
        for identity in ("service", "system", "dataset", "fault", "root", "label"):
            self.assertFalse(any(identity in name.lower() for name in schema["selected_columns"]))

    def test_top5_membership_is_preserved(self):
        ranking = {"i": [{"service": str(n), "rank": n, "score": 10-n} for n in range(1, 9)]}
        scores = {("i", str(n)): float(n) for n in range(1, 6)}
        output = rerank_top_k(ranking, scores, 5)["i"]
        self.assertEqual({str(n) for n in range(1, 6)}, {i["service"] for i in output[:5]})
        self.assertEqual(["6", "7", "8"], [i["service"] for i in output[5:]])

    def test_full_denominator_and_missing_candidate(self):
        from rca_ml.m12_evaluate import metrics
        predictions = {"a": [{"service": "x", "rank": 1}], "b": [{"service": "x", "rank": 1}]}
        truth = {"a": {"root_service": "x"}, "b": {"root_service": "missing"}}
        result = metrics(predictions, truth)
        self.assertEqual(2, result["incidents"])
        self.assertEqual(.5, result["ac_at_1"])
        self.assertEqual(.5, result["candidate_universe_coverage"])

    def test_cluster_bootstrap_is_deterministic(self):
        truth = {str(i): {"root_service": "a" if i < 2 else "b", "fault_family": "cpu"} for i in range(4)}
        good = {i: [{"service": truth[i]["root_service"], "rank": 1}] for i in truth}
        bad = {i: [{"service": "z", "rank": 1}] for i in truth}
        self.assertEqual(paired_bootstrap(good, bad, truth, "mrr", cluster=True), paired_bootstrap(good, bad, truth, "mrr", cluster=True))

    def test_training_count_is_frozen_zero(self):
        self.assertEqual(0, json.loads((ROOT / "ml/models/m12/preflight.json").read_text())["model_training_count_required"])
        ood = json.loads((ROOT / "ml/models/m12/ood-stats.json").read_text())
        self.assertEqual(0, ood["m12_incidents"])

    def test_wilson_bounds(self):
        low, high = wilson(7, 10)
        self.assertLess(low, .7); self.assertGreater(high, .7)


if __name__ == "__main__":
    unittest.main()
