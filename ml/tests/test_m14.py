import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rca_ml.m14_evaluate import decide_verdict
from rca_ml.m14_runtime import FrozenM13TransferRuntime


def comparison(ac=False, mrr=False):
    return {
        "ac_at_1": {"cluster": {"supported_positive": ac}},
        "mrr": {"cluster": {"supported_positive": mrr}},
    }


def metric(ac1=.8, ac3=.9, ac5=.95, coverage=1.0, mrr=.85):
    return {"ac_at_1": ac1, "ac_at_3": ac3, "ac_at_5": ac5, "candidate_universe_coverage": coverage, "mrr": mrr}


class VerdictTest(unittest.TestCase):
    def test_strong_transfer_uses_all_preregistered_gates(self):
        pooled = {"frozen_m13": metric(), "chance": metric(mrr=.2)}
        comparisons = {name: comparison(mrr=True) for name in ("chance", "metric_heuristic", "frozen_m11")}
        per_fault = {name: {"frozen_m13": metric()} for name in ("cpu", "memory", "network_latency", "packet_loss", "service_unavailable")}
        verdict, gates = decide_verdict(pooled, comparisons, per_fault)
        self.assertEqual("STRONG_TRANSFER", verdict)
        self.assertTrue(gates["no_majority_fault_catastrophe"])

    def test_limited_transfer_when_strong_baselines_are_not_beaten(self):
        pooled = {"frozen_m13": metric(ac1=.2, ac3=.4, ac5=.6, mrr=.3), "chance": metric(mrr=.2)}
        comparisons = {name: comparison() for name in ("chance", "metric_heuristic", "frozen_m11")}
        per_fault = {"cpu": {"frozen_m13": metric(ac5=.6)}}
        self.assertEqual("LIMITED_TRANSFER", decide_verdict(pooled, comparisons, per_fault)[0])


class RuntimeBoundaryTest(unittest.TestCase):
    def test_candidate_universe_drift_is_rejected_before_features(self):
        runtime = object.__new__(FrozenM13TransferRuntime)
        runtime.services = ("a", "b")
        with self.assertRaisesRegex(RuntimeError, "candidate universe drift"):
            runtime.rank_all({"incident_id": "x", "candidate_services": ["a"]})


class ProtocolTest(unittest.TestCase):
    def test_locked_plan_has_50_incidents_and_25_clusters(self):
        root = Path(__file__).resolve().parents[2]
        namespace = {}
        source = (root / "scripts/m14/run.py").read_text()
        self.assertIn('"expected_incidents": 50', (root / "deploy/m14/config.json").read_text())
        config = json.loads((root / "deploy/m14/config.json").read_text())
        self.assertEqual(5, len(config["target_services"]))
        self.assertEqual(5, len(config["fault_families"]))
        self.assertEqual(2, config["incident"]["repetitions_per_cluster"])


if __name__ == "__main__":
    unittest.main()
