"""Product-only inference must remain bit-identical to the accepted research path."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from profile_runtime import ProfileTransferRuntime
from runtime_assets import EXPECTED_SHA256
from server import DiagnosticApplication

ROOT = Path(__file__).resolve().parents[2]


class ProductInferenceRegressionTests(unittest.TestCase):
    def test_all_available_saved_inputs_match_scores_and_evidence_without_comparator_models(self):
        app = DiagnosticApplication(ROOT)
        runtime = ProfileTransferRuntime(ROOT, ROOT / "ml/models/m14", app.runtime.services)
        expected = json.loads((ROOT / "ml/models/m14/evaluation-inputs.json").read_text())["predictions"]["frozen_m13"]
        self.assertTrue(app.examples, "at least the shipped regression case is required")
        for identifier in app.examples:
            window = {key: value for key, value in app.example(identifier).items() if key != "workload_result"}
            actual = app.analyze(window, runtime)
            self.assertEqual([(x["rank"], x["service"], x["model_score"]) for x in actual["candidates"]],
                             [(x["rank"], x["service"], x["score"]) for x in expected[identifier]], identifier)
            legacy = app.analyze(window)
            self.assertEqual(actual["candidates"], legacy["candidates"], identifier)

    def test_every_inference_artifact_is_verified_before_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in EXPECTED_SHA256:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            for name in EXPECTED_SHA256:
                with self.subTest(artifact=name):
                    target = root / name
                    original = target.read_bytes()
                    target.write_bytes(original + b" ")
                    with self.assertRaisesRegex(RuntimeError, "runtime artifact checksum differs"):
                        ProfileTransferRuntime(root, ROOT / "ml/models/m14", ("candidate",))
                    target.write_bytes(original)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), EXPECTED_SHA256[name])
