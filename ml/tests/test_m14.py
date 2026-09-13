import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rca_ml.m14_evaluate import decide_verdict
from rca_ml.m14_runtime import FrozenM13TransferRuntime

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m14_collection", ROOT / "scripts/m14/run.py")
collection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collection)


class HealthyWorkloadTest(unittest.TestCase):
    def result(self, status):
        return {"returncode": 0, "stdout": json.dumps({
            "statuses": {str(status): 6}, "attempts": 6,
            "dispatch_rate": 6, "requests_per_second": 6,
        })}

    def test_client_errors_cannot_be_a_healthy_baseline(self):
        for status in (0, 301, 404, 422, 500):
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                collection.validate_workload(self.result(status), phase="healthy")

    def test_expected_fault_errors_remain_in_denominator(self):
        self.assertEqual(6, collection.validate_workload(
            self.result(500), phase="fault", allow_failures=True)["attempts"])
        self.assertEqual(6, collection.validate_workload(
            self.result(200), phase="healthy")["attempts"])


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
        plan = collection.plan()
        self.assertEqual(json.loads((root / "ml/models/m14/incident-plan.json").read_text()), plan)
        self.assertEqual(50, len(plan["incidents"]))
        self.assertEqual(25, len({(item["root_service"], item["fault_family"]) for item in plan["incidents"]}))


if __name__ == "__main__":
    unittest.main()
