"""Product regression checks without changing the sealed research artifacts."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import DiagnosticApplication, is_loopback_host, make_handler


ROOT = Path(__file__).resolve().parents[2]


class DiagnosticApplicationTests(unittest.TestCase):
    def test_public_bind_requires_explicit_opt_in(self):
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertTrue(is_loopback_host("localhost"))
        self.assertFalse(is_loopback_host("0.0.0.0"))
        self.assertFalse(is_loopback_host("192.0.2.10"))
        self.assertFalse(is_loopback_host("diagnostics.example.org"))

    @classmethod
    def setUpClass(cls):
        cls.app = DiagnosticApplication(ROOT)
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=5)

    def request(self, path: str, payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=body, headers={"Content-Type": "application/json"} if body else {})
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)

    def test_health_and_examples(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["model_count"], 5)
        self.assertEqual(health["examples"], 50)
        _, examples = self.request("/api/examples")
        self.assertEqual(len(examples), 50)
        self.assertNotIn("root_service", examples[0])

    def test_http_analysis_matches_sealed_prediction(self):
        case_id = next(iter(self.app.examples))
        _, actual = self.request("/api/analyze", {"example_id": case_id})
        expected = json.loads((ROOT / "ml/models/m14/evaluation-inputs.json").read_text())["predictions"]["frozen_m13"][case_id]
        self.assertEqual(len(actual["candidates"]), 12)
        source = self.app.example(case_id)
        self.assertEqual(actual["incident_id"], source["incident_id"])
        self.assertEqual(actual["start_unix"], source["start_unix"])
        self.assertEqual(actual["end_unix"], source["end_unix"])
        self.assertEqual(actual["model_version"], self.app.runtime.freeze["version"])
        self.assertEqual(
            [(item["rank"], item["service"], item["model_score"]) for item in actual["candidates"]],
            [(item["rank"], item["service"], item["score"]) for item in expected],
        )
        self.assertNotIn("root_service", actual)

    def test_uploaded_window_and_forbidden_truth(self):
        case_id = next(iter(self.app.examples))
        incident = {key: value for key, value in self.app.example(case_id).items() if key != "workload_result"}
        _, uploaded = self.request("/api/analyze", {"incident": incident})
        self.assertEqual(uploaded["candidate_count"], 12)
        self.assertEqual(uploaded["start_unix"], incident["start_unix"])
        self.assertEqual(uploaded["end_unix"], incident["end_unix"])
        incident["root_service"] = "recommendation"
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/analyze", {"incident": incident})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_invalid_interval_is_rejected(self):
        case_id = next(iter(self.app.examples))
        incident = {key: value for key, value in self.app.example(case_id).items() if key != "workload_result"}
        incident["end_unix"] = incident["start_unix"]
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/analyze", {"incident": incident})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

        incident["end_unix"] = 10_000_000_000_000
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/analyze", {"incident": incident})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_all_examples_match_sealed_ranks(self):
        expected = json.loads((ROOT / "ml/models/m14/evaluation-inputs.json").read_text())["predictions"]["frozen_m13"]
        for case_id in self.app.examples:
            incident = {key: value for key, value in self.app.example(case_id).items() if key != "workload_result"}
            actual = self.app.analyze(incident)
            self.assertEqual(
                [(item["rank"], item["service"], item["model_score"]) for item in actual["candidates"]],
                [(item["rank"], item["service"], item["score"]) for item in expected[case_id]],
                case_id,
            )


if __name__ == "__main__":
    unittest.main()
