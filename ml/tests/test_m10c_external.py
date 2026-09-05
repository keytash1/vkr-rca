import json
import unittest
from pathlib import Path


class M10CExternalTests(unittest.TestCase):
    def test_cloud_ops_compatibility_is_label_isolated(self):
        root = Path(__file__).resolve().parents[2]
        document = json.loads((root / "artifacts/m10c/m10c-v2/external-stress.json").read_text())
        cloud = document["cloud_ops_bench"]
        self.assertFalse(cloud["label_used_for_tuning"])
        self.assertEqual(cloud["result"], "COMPATIBILITY_ONLY")

    def test_torai_non_result_is_not_presented_as_accuracy(self):
        root = Path(__file__).resolve().parents[2]
        torai = json.loads((root / "artifacts/m10c/m10c-v2/external-stress.json").read_text())["torai"]
        self.assertIsNone(torai["runtime_seconds"])
        self.assertTrue(torai["result"].startswith("NOT_RUN"))


if __name__ == "__main__":
    unittest.main()
