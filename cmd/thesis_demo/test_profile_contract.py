"""Meaningful configuration changes invalidate a newly bound baseline."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from live_sources import LiveProfile
from profile_contract import baseline_binding, contract_sha256, validate_semantic_map
from rca_ml.m12_adapter import CANONICAL_UNITS
from profile_test_fixtures import profile_document


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        draft = self.directory / "profile.json"
        draft.write_text(json.dumps(profile_document()))
        self.profile = replace(
            LiveProfile.load(draft, self.directory, require_artifacts=False),
            artifact_dir=self.directory,
        )

    def bind(self):
        hashes = {}
        for name in ("healthy-baseline.json", "legacy-metric-baseline.json"):
            (self.directory / name).write_bytes(b"{}\n")
            hashes[name] = hashlib.sha256(b"{}\n").hexdigest()
        (self.directory / "provenance.json").write_text(
            json.dumps(
                {
                    "profile_contract_sha256": contract_sha256(self.profile),
                    "files_sha256": hashes,
                }
            )
        )

    def test_legacy_marked_not_forged(self):
        self.assertEqual(baseline_binding(self.profile)["state"], "needs_review")
        (self.directory / "provenance.json").write_text("{}")
        self.assertEqual(baseline_binding(self.profile)["state"], "needs_review")

    def test_bound_profile_change_guards(self):
        self.bind()
        self.assertEqual(baseline_binding(self.profile)["state"], "active")
        display = replace(
            self.profile,
            title="New title",
            version="display version",
            trace_version="newly tested backend version",
        )
        self.assertEqual(contract_sha256(display), contract_sha256(self.profile))
        changes = [
            dict(services=("different",)),
            dict(aliases={"replica": self.profile.services[0]}),
            dict(metrics_url="http://127.0.0.1:9999"),
            dict(metric_service_label="application"),
            dict(metric_queries=self.profile.metric_queries | {"cpu": "different"}),
            dict(query_step_seconds=30),
            dict(trace_contract="jaeger-v3-json"),
            dict(fixed_rps=1.0, rps_query=None),
        ]
        for change in changes:
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "semantic contract differs"),
            ):
                baseline_binding(replace(self.profile, **change))

    def test_checksums_required_and_tamper_rejected(self):
        self.bind()
        (self.directory / "healthy-baseline.json").write_bytes(b"{} ")
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            baseline_binding(self.profile)
        self.bind()
        p = self.directory / "provenance.json"
        raw = json.loads(p.read_text())
        raw["files_sha256"] = {}
        p.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "both file checksums"):
            baseline_binding(self.profile)

    def test_semantic_map_requires_units_and_reset_policy(self):
        mapping = {
            family: dict(
                source_kind="derived",
                source_unit=unit,
                canonical_unit=unit,
                transformation="profile query",
                replica_aggregation="sum by service",
                counter_reset_policy="not_applicable",
            )
            for family, unit in CANONICAL_UNITS.items()
        }
        self.assertEqual(validate_semantic_map(mapping), mapping)
        mapping["cpu"]["canonical_unit"] = "percent"
        with self.assertRaisesRegex(ValueError, "canonical unit differs"):
            validate_semantic_map(mapping)
        mapping["cpu"]["canonical_unit"] = CANONICAL_UNITS["cpu"]
        mapping["cpu"]["source_kind"] = "counter"
        with self.assertRaisesRegex(ValueError, "reset handling"):
            validate_semantic_map(mapping)


if __name__ == "__main__":
    unittest.main()
