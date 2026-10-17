"""No silent profile mutation, candidate shrinkage or baseline replacement."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_sources import LiveProfile
from profile_contract import contract_sha256
from profile_onboarding import activate, inspect_profile
from rca_ml.m12_adapter import CANONICAL_UNITS
from profile_test_fixtures import profile_document


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = profile_document()
        self.raw["metrics"]["semantic_map"] = {
            f: dict(
                source_kind="derived",
                source_unit=u,
                canonical_unit=u,
                transformation="reviewed profile query",
                replica_aggregation="sum by service",
                counter_reset_policy="handled in rate before aggregation",
            )
            for f, u in CANONICAL_UNITS.items()
        }
        self.draft = self.root / "draft.json"
        self.active = self.root / "profiles/synthetic.json"
        self.make_draft("first")

    def make_draft(self, version):
        self.raw["version"] = version
        self.raw["artifact_dir"] = f"deploy/profiles/artifacts/{version}"
        self.draft.write_text(json.dumps(self.raw))
        profile = LiveProfile.load(self.draft, self.root, require_artifacts=False)
        profile.artifact_dir.mkdir(parents=True)
        hashes = {}
        for name, value in {
            "healthy-baseline.json": {
                "metric": {s: {} for s in profile.services},
                "trace": {s: {} for s in profile.services},
            },
            "legacy-metric-baseline.json": {},
        }.items():
            data = json.dumps(value).encode()
            (profile.artifact_dir / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (profile.artifact_dir / "provenance.json").write_text(
            json.dumps(
                {
                    "profile_contract_sha256": contract_sha256(profile),
                    "files_sha256": hashes,
                }
            )
        )

    def test_activate_cas_and_rollback(self):
        first = activate(self.root, self.draft, self.active, "absent")
        original = self.active.read_bytes()
        self.assertIsNone(first["rollback_profile"])
        self.make_draft("second")
        with self.assertRaisesRegex(ValueError, "changed"):
            activate(self.root, self.draft, self.active, "absent")
        second = activate(
            self.root, self.draft, self.active, first["active_profile_sha256"]
        )
        self.assertNotEqual(self.active.read_bytes(), original)
        self.assertEqual(Path(second["rollback_profile"]).read_bytes(), original)
        rollback = activate(
            self.root,
            Path(second["rollback_profile"]),
            self.active,
            second["active_profile_sha256"],
        )
        self.assertEqual(self.active.read_bytes(), original)
        self.assertEqual(rollback["state"], "active_after_process_restart")

    def test_changed_meaning_or_missing_map_cannot_activate(self):
        self.raw["metrics"]["queries"]["cpu"] = "different expression"
        self.draft.write_text(json.dumps(self.raw))
        with self.assertRaisesRegex(ValueError, "semantic contract differs"):
            activate(self.root, self.draft, self.active, "absent")
        self.assertFalse(self.active.exists())

    def test_discovery_is_proposal_and_never_drops_missing(self):
        before = self.draft.read_bytes()
        series = [{"metric": {"service": "new-service"}, "values": [[1700000000, "1"]]}]
        with patch("profile_onboarding._prometheus", return_value=series):
            report = inspect_profile(self.root, self.draft, 1700000000, 1700000060)
        self.assertEqual(self.draft.read_bytes(), before)
        self.assertEqual(report["unmapped_observed_services"], ["new-service"])
        self.assertEqual(
            set(report["proposed_candidates"]),
            set(self.raw["candidate_services"]) | {"new-service"},
        )
        self.assertEqual(
            report["configured_services_not_observed"], self.raw["candidate_services"]
        )

    def test_outside_target_and_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the installation"):
            activate(
                self.root, self.draft, self.root.parent / "forbidden.json", "absent"
            )
        link = self.root / "link.json"
        link.symlink_to(self.draft)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            activate(self.root, link, self.active, "absent")


if __name__ == "__main__":
    unittest.main()
