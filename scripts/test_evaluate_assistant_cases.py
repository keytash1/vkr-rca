import copy
import json
from pathlib import Path
import tempfile
import unittest

from evaluate_assistant_cases import load_completed_assignments, sha, wire


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.config = {"frozen": "module-hashes"}
        self.plan = [("case-1", 1, "C"), ("case-1", 1, "D")]
        self.write("configuration.json", self.config)
        self.write("assigned-attempts.json", self.plan)
        self.start = {"attempt_id": "case-1-C-r1", "configuration_sha256": sha(wire(self.config)),
            "input_file_sha256": "input", "started_at_unix": 123}
        self.write("case-1-C-r1-started.json", self.start)
        self.result = self.start | {"outcome": {"status": "failed", "usage": {
            "known_input_tokens": 0, "known_output_tokens": 0, "unaccounted_attempts": 1}}}
        self.write("case-1-C-r1.json", self.result)

    def write(self, name, value):
        (self.path / name).write_bytes(wire(value))

    def test_failed_unknown_is_retained_not_retried_or_zeroed(self):
        before = {p.name: p.read_bytes() for p in self.path.iterdir()}
        done, totals = load_completed_assignments(self.path, self.config, self.plan)
        self.assertEqual(done, {"case-1-C-r1"})
        self.assertEqual(totals, dict(count=1, failures=1, input=0, output=0, unknown=1))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.path.iterdir()})

    def test_changed_config_or_assignments_rejected(self):
        for config, plan in (({"frozen": "changed"}, self.plan), (self.config, self.plan[::-1])):
            with self.assertRaises(ValueError):
                load_completed_assignments(self.path, config, plan)

    def test_started_only_never_retried(self):
        self.write("case-1-D-r1-started.json", self.start | {"attempt_id": "case-1-D-r1"})
        with self.assertRaisesRegex(ValueError, "unresolved"):
            load_completed_assignments(self.path, self.config, self.plan)

    def test_nonprefix_and_forged_provenance_rejected(self):
        self.write("case-1-C-r1.json", self.result | {"input_file_sha256": "changed"})
        with self.assertRaisesRegex(ValueError, "mismatch"):
            load_completed_assignments(self.path, self.config, self.plan)
        (self.path / "case-1-C-r1.json").unlink()
        (self.path / "case-1-C-r1-started.json").unlink()
        self.write("case-1-D-r1.json", self.result)
        self.write("case-1-D-r1-started.json", self.start)
        with self.assertRaisesRegex(ValueError, "prefix"):
            load_completed_assignments(self.path, self.config, self.plan)


if __name__ == "__main__":
    unittest.main()
