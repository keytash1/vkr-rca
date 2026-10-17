"""Research-only regression: excluded from the experiment-free product repo."""

import json
from pathlib import Path
import unittest

from api_contract import SCHEMAS
from evidence_catalog import EvidenceRegistry, assistant_context
from server import DiagnosticApplication

ROOT = Path(__file__).resolve().parents[2]

class CatalogRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = DiagnosticApplication(ROOT)

    def test_v1_ranks_unchanged_and_catalog_does_not_contain_truth(self):
        case = next(iter(self.app.examples))
        window = {k: v for k, v in self.app.example(case).items() if k != "workload_result"}
        result = self.app.analyze(window)
        catalog = self.app.evidence_registry.get(result["result_id"])
        self.assertIsNotNone(catalog)
        self.assertEqual(catalog["input_sha256"], result["input_sha256"])
        expected = json.loads((ROOT / "ml/models/m14/evaluation-inputs.json").read_text())["predictions"]["frozen_m13"][case]
        self.assertEqual([(c["service"], c["rank"], c["model_score"]) for c in result["candidates"]],
                         [(c["service"], c["rank"], c["score"]) for c in expected])
        self.assertEqual(assistant_context(catalog)["services"], sorted(window["candidate_services"]))
        self.assertEqual(set(result), set(SCHEMAS["AnalysisResult"]["required"]))

    def test_presentation_budget_does_not_break_primary_analysis(self):
        app = DiagnosticApplication(ROOT)
        app.evidence_registry = EvidenceRegistry(max_entry_bytes=1)
        case = next(iter(app.examples))
        window = {k: v for k, v in app.example(case).items() if k != "workload_result"}
        result = app.analyze(window)
        self.assertEqual(result["candidate_count"], len(app.runtime.services))
        self.assertIsNone(app.evidence_registry.get(result["result_id"]))

    def test_every_available_regression_input_has_a_scoped_catalog(self):
        for case in self.app.examples:
            with self.subTest(case=case):
                window = {k: v for k, v in self.app.example(case).items() if k != "workload_result"}
                result = self.app.analyze(window)
                catalog = self.app.evidence_registry.get(result["result_id"])
                self.assertIsNotNone(catalog)
                self.assertEqual(catalog["input_sha256"], result["input_sha256"])
                self.assertEqual(catalog["services"], sorted(window["candidate_services"]))
                self.assertNotIn("ranking_hint", assistant_context(catalog))


if __name__ == "__main__":
    unittest.main()
