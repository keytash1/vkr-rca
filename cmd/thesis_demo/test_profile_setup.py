"""Profile onboarding must work without changing the frozen ranking models."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from profile_setup import prepare
from profile_runtime import ProfileTransferRuntime
from rca_ml.m12_adapter import CANONICAL_UNITS

ROOT = Path(__file__).resolve().parents[2]


class ProfileSetupTests(unittest.TestCase):
    def test_fit_new_system_and_refuse_implicit_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile_path = root / "new-system.json"
            profile_path.write_text(json.dumps({
                "id": "new-system", "title": "Новая система", "version": "1",
                "candidate_services": ["api", "worker"],
                "artifact_dir": "deploy/profiles/artifacts/new-system",
                "metrics": {"url": "http://127.0.0.1:1", "service_label": "service",
                            "queries": {family: family for family in CANONICAL_UNITS}},
                "traces": {"url": "http://127.0.0.1:1", "query_services": ["api"]},
                "workload": {"fixed_requests_per_second": 4},
            }))
            metrics = [
                {"timestamp": timestamp, "service": service, "family": family,
                 "value": 1.0, "unit": CANONICAL_UNITS[family]}
                for service in ("api", "worker") for family in CANONICAL_UNITS
                for timestamp in range(1_700_000_000, 1_700_000_101)
            ]
            trace = {"trace_id": "healthy-1", "span_id": "span-1", "parent_span_id": None,
                     "service": "api", "peer_service": None, "span_kind": "SERVER",
                     "start_time_us": 1_700_000_010_000_000, "duration_us": 10_000,
                     "status_code": "OK", "error": False}
            window = {"requests_per_second": 4.0, "metrics": metrics,
                      "traces": [trace, trace | {"service": "worker", "span_id": "span-2"}]}
            status = {
                "traces": "available",
                "metric_families_by_service": {
                    service: list(CANONICAL_UNITS) for service in ("api", "worker")
                },
            }
            with patch("profile_setup.collect", return_value=(window, status)):
                result = prepare(root, profile_path, 1_700_000_000, 1_700_000_100)
                self.assertEqual(result["profile_id"], "new-system")
                self.assertEqual(result["workload_reference"]["requests_per_second"], 4)
                self.assertEqual(result["workload_reference"]["source"], "profile_constant")
                baseline_dir = root / "deploy/profiles/artifacts/new-system"
                baseline = json.loads((baseline_dir / "healthy-baseline.json").read_text())
                self.assertEqual(set(baseline["metric"]), {"api", "worker"})
                self.assertGreater(baseline["windows"], 0)
                self.assertTrue((baseline_dir / "provenance.json").is_file())
                runtime = ProfileTransferRuntime(ROOT, baseline_dir, ("api", "worker"))
                ranked = runtime.rank_all(window | {
                    "incident_id": "new-system-incident",
                    "start_unix": 1_700_000_000,
                    "end_unix": 1_700_000_100,
                    "candidate_services": ["api", "worker"],
                    "traces_collected": True,
                })["frozen_m13"]
                self.assertEqual({item["service"] for item in ranked}, {"api", "worker"})
                with self.assertRaises(FileExistsError):
                    prepare(root, profile_path, 1_700_000_000, 1_700_000_100)
                damaged = baseline_dir / "healthy-baseline.json"
                damaged.write_text(damaged.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "checksum differs"):
                    ProfileTransferRuntime(ROOT, baseline_dir, ("api", "worker"))


if __name__ == "__main__":
    unittest.main()
