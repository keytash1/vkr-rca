import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rca_ml.m10c_integrity import FROZEN_SHA256, sha256_file, verify_frozen


class M10CIntegrityTests(unittest.TestCase):
    def test_repository_frozen_inputs_are_unchanged(self):
        root = Path(__file__).resolve().parents[2]
        result = verify_frozen(root)
        self.assertTrue(result["ok"], result["mismatches"])
        self.assertEqual(result["checked_files"], len(FROZEN_SHA256))

    def test_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {}
            for name in FROZEN_SHA256:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
                expected[name] = sha256_file(path)
            with patch("rca_ml.m10c_integrity.FROZEN_SHA256", expected):
                self.assertTrue(verify_frozen(root)["ok"])
                first = root / next(iter(expected))
                first.write_text("mutated")
                self.assertFalse(verify_frozen(root)["ok"])


if __name__ == "__main__":
    unittest.main()

