"""Checks for the read-only profile preflight command."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from profile_check import check_profile, parse_time


ROOT = Path(__file__).resolve().parents[2]


class ProfileCheckTests(unittest.TestCase):
    def test_complete_source_is_ready_for_baseline(self):
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        families = {service: ["cpu", "memory", "network", "traffic_rate"]
                    for service in profile["candidate_services"]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile))
            metrics = [{"service": service, "family": family, "timestamp": timestamp}
                       for service, groups in families.items() for family in groups
                       for timestamp in range(100, 201)]
            with patch("profile_check.collect", return_value=(
                {"traces": [{"service": service} for service in profile["candidate_services"]], "metrics": metrics},
                {"metrics": "available", "traces": "available",
                 "metric_families_by_service": families,
                 "metric_sample_count": 120, "span_count": 1},
            )):
                result = check_profile(ROOT, path, 100, 200, baseline=True)
        self.assertEqual(result["verdict"], "ready")
        self.assertEqual(result["candidate_count"], 12)

    def test_one_trace_entry_does_not_prove_all_healthy_candidates_are_observed(self):
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        families = {service: ["cpu", "memory", "network", "traffic_rate"] for service in profile["candidate_services"]}
        metrics = [{"service": service, "family": family, "timestamp": timestamp}
                   for service, groups in families.items() for family in groups for timestamp in range(100, 201)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile))
            with patch("profile_check.collect", return_value=(
                {"metrics": metrics, "traces": [{"service": "frontend"}]},
                {"metrics": "available", "traces": "available", "metric_families_by_service": families},
            )):
                result = check_profile(ROOT, path, 100, 200, baseline=True)
        self.assertEqual(result["verdict"], "not_ready_for_baseline")
        self.assertIn("healthy traces are missing", " ".join(result["issues"]))

    def test_one_point_per_family_does_not_make_a_healthy_baseline(self):
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        families = {service: ["cpu", "memory", "network", "traffic_rate"]
                    for service in profile["candidate_services"]}
        metrics = [{"service": service, "family": family, "timestamp": 150}
                   for service, groups in families.items() for family in groups]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile))
            with patch("profile_check.collect", return_value=(
                {"metrics": metrics, "traces": [{"service": "frontend"}]},
                {"metrics": "available", "traces": "available",
                 "metric_families_by_service": families,
                 "metric_sample_count": len(metrics), "span_count": 1},
            )):
                result = check_profile(ROOT, path, 100, 200, baseline=True)
        self.assertEqual(result["verdict"], "not_ready_for_baseline")
        self.assertIn("insufficient returned metric-point coverage", " ".join(result["issues"]))

    def test_incomplete_source_is_not_baseline_ready(self):
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        families = {service: [] for service in profile["candidate_services"]}
        families["frontend"] = ["cpu"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile))
            with patch("profile_check.collect", return_value=(
                {"traces": []},
                {"metrics": "available", "traces": "unavailable",
                 "metric_families_by_service": families,
                 "metric_sample_count": 1, "span_count": 0},
            )):
                baseline = check_profile(ROOT, path, 100, 200, baseline=True)
                incident = check_profile(ROOT, path, 100, 200)
        self.assertEqual(baseline["verdict"], "not_ready_for_baseline")
        self.assertEqual(incident["verdict"], "degraded_incident_input")
        self.assertEqual(baseline["missing_metric_families"]["frontend"],
                         ["memory", "network", "traffic_rate"])

    def test_timezone_is_required(self):
        with self.assertRaises(ValueError):
            parse_time("2026-10-16T10:00:00")


if __name__ == "__main__":
    unittest.main()
