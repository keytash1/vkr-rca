"""Acceptance evidence may not treat an absent counter as zero failures."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest

spec = spec_from_file_location("acceptance_protocol", Path(__file__).resolve().parents[2] / "scripts/accept_live_profile.py")
protocol = module_from_spec(spec)
spec.loader.exec_module(protocol)


def response(value):
    return {"status": "success", "data": {"result": [{"value": [100, str(value)]}]}}


class WorkloadEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.health = {key: response(value) for key, value in
                       {"started": 100, "succeeded": 99, "failed": 0, "dropped": 0}.items()}

    def test_all_counters_observed_and_active(self):
        self.assertEqual(protocol.verify_healthy_workload(self.health)["failed"], 0)

    def test_unknown_counters_are_not_zero_failures(self):
        for invalid in ({"status": "success", "data": {"result": []}},
                        response("NaN"), response(-1), {}):
            with self.subTest(invalid=invalid):
                self.health["dropped"] = invalid
                with self.assertRaisesRegex(RuntimeError, "counter 'dropped'"):
                    protocol.verify_healthy_workload(self.health)

    def test_errors_or_no_activity_are_not_healthy(self):
        for name, value in (("failed", 1), ("dropped", 1), ("started", 0), ("succeeded", 0)):
            with self.subTest(name=name):
                health = self.health | {name: response(value)}
                with self.assertRaises(RuntimeError):
                    protocol.verify_healthy_workload(health)
