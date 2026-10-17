"""The published API must match real handlers, including error semantics."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from api_contract import document
from server import DiagnosticApplication, MAX_UPLOAD_BYTES, make_handler
from test_live import FakeTelemetry
from live_sources import TelemetrySourceError

ROOT = Path(__file__).resolve().parents[2]


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelemetry)
        cls.source_thread = threading.Thread(target=cls.source.serve_forever, daemon=True)
        cls.source_thread.start()
        cls.temp = tempfile.TemporaryDirectory()
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        profile["metrics"]["url"] = f"http://127.0.0.1:{cls.source.server_port}"
        profile["metrics"]["queries"] = {name: name for name in profile["metrics"]["queries"]}
        profile["traces"]["url"] = profile["metrics"]["url"]
        directory = Path(cls.temp.name)
        (directory / "valid.json").write_text(json.dumps(profile))
        (directory / "broken.json").write_text('{"id": "broken"}')
        cls.app = DiagnosticApplication(ROOT, directory)
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        cls.payload = {"profile_id": "lab-system", "start_unix": 1700000000, "end_unix": 1700000030}

    @classmethod
    def tearDownClass(cls):
        for server, thread in ((cls.http, cls.thread), (cls.source, cls.source_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, payload=None, path="/api/analyze", headers=None):
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            response = urlopen(Request(self.base + path, data=body,
                headers=headers or ({"Content-Type": "application/json"} if body else {})), timeout=15)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), dict(response.headers)

    def check_schema(self, value, name):
        Draft202012Validator({"$ref": f"#/components/schemas/{name}",
                              "components": document()["components"]}).validate(value)

    def test_openapi_and_real_result(self):
        status, spec, _ = self.request(path="/api/openapi.json")
        self.assertEqual(status, 200)
        validate(spec)
        self.check_schema(self.payload, "LiveAnalysisRequest")
        status, result, _ = self.request(self.payload)
        self.assertEqual(status, 200)
        self.check_schema(result, "AnalysisResult")
        self.assertGreater(result["timing"]["total_seconds"], 0)
        self.assertEqual(len(result["input_sha256"]), 64)
        self.assertLess(result["source_status"]["metric_point_coverage"]["frontend"]["cpu"], 1)
        status, catalog, headers = self.request(path=f'/api/v2/analyses/{result["result_id"]}/evidence')
        self.assertEqual(status, 200)
        self.check_schema(catalog, "EvidenceCatalog")
        self.assertEqual(catalog["input_sha256"], result["input_sha256"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(catalog["services"], sorted(c["service"] for c in result["candidates"]))
        for suffix in ("unknown/evidence", f'{result["result_id"]}/extra/evidence'):
            status, error, _ = self.request(path="/api/v2/analyses/" + suffix)
            self.assertEqual(status, 404)
            self.check_schema(error, "Error")

    def test_stable_validation_errors(self):
        cases = [([], "INVALID_REQUEST", 400),
                 (self.payload | {"extra": 1}, "INVALID_REQUEST", 400),
                 (self.payload | {"profile_id": "unknown"}, "PROFILE_UNKNOWN", 404),
                 (self.payload | {"profile_id": []}, "INVALID_REQUEST", 400),
                 (self.payload | {"end_unix": self.payload["start_unix"]}, "INVALID_INTERVAL", 400),
                 (self.payload | {"end_unix": self.payload["start_unix"] + 3601}, "INVALID_INTERVAL", 400),
                 (self.payload | {"start_unix": time.time(), "end_unix": time.time() + 100}, "INVALID_INTERVAL", 400)]
        for payload, expected, status in cases:
            with self.subTest(code=expected, payload=payload):
                actual_status, error, _ = self.request(payload)
                self.assertEqual(actual_status, status)
                self.assertEqual(error["code"], expected)
                self.check_schema(error, "Error")
                self.assertNotIn("candidates", error)

    def test_base_local_api_rejects_rebinding_and_cross_origin_before_collection(self):
        for headers, code in (({"Host":"attacker.invalid"}, "HOST_NOT_ALLOWED"),
                              ({"Origin":"https://attacker.invalid"}, "ORIGIN_NOT_ALLOWED"),
                              ({"Sec-Fetch-Site":"cross-site"}, "ORIGIN_NOT_ALLOWED")):
            with self.subTest(headers=headers), patch.object(self.app,"analyze_live") as analyze:
                status, error, _ = self.request(self.payload, headers=headers | {"Content-Type":"application/json"})
                self.assertEqual((status,error["code"]),(403,code))
                analyze.assert_not_called()
                self.assertEqual(self.request(path="/api/health",headers=headers)[0],403)

    def test_busy_request_does_not_queue_or_corrupt_next_request(self):
        self.app.analysis_slot.acquire()
        try:
            status, error, headers = self.request(self.payload)
            self.assertEqual(status, 429)
            self.assertEqual(error["code"], "REQUEST_BUSY")
            self.assertEqual(headers["Retry-After"], "2")
        finally:
            self.app.analysis_slot.release()
        self.assertEqual(self.request(self.payload)[0], 200)

    def test_failure_does_not_leak_secrets(self):
        with patch.object(self.app, "analyze_live", side_effect=RuntimeError("token=super-secret")):
            status, error, _ = self.request(self.payload)
        self.assertEqual(status, 500)
        self.assertEqual(error["code"], "INTERNAL_ERROR")
        self.assertNotIn("super-secret", json.dumps(error))
        self.assertEqual(self.request(self.payload)[0], 200)

    def test_source_data_errors_and_deadlines_are_not_user_input_errors(self):
        for exception, status, code in ((TelemetrySourceError("invalid workload"), 502, "TELEMETRY_INVALID"),
                                        (TimeoutError("expired source deadline"), 504, "SOURCE_TIMEOUT")):
            with self.subTest(code=code), patch.object(self.app, "analyze_live", side_effect=exception):
                actual, error, _ = self.request(self.payload)
                self.assertEqual((actual, error["code"]), (status, code))
                self.assertNotIn("candidates", error)
                self.check_schema(error, "Error")

    def test_invalid_profile_does_not_break_valid_one(self):
        _, health, _ = self.request(path="/api/health")
        self.assertIn("broken", health["profile_errors"])
        self.assertEqual(health["profiles"], 1)
        _, profiles, _ = self.request(path="/api/profiles")
        self.assertEqual([p["id"] for p in profiles], ["lab-system"])
        self.assertEqual(self.request(self.payload)[0], 200)

    def test_media_type_and_payload_limit(self):
        status, error, _ = self.request(self.payload, headers={"Content-Type": "text/plain"})
        self.assertEqual((status, error["code"]), (415, "MEDIA_TYPE_UNSUPPORTED"))
        status, error, _ = self.request(self.payload, headers={"Content-Type": "application/json", "Content-Length": str(MAX_UPLOAD_BYTES + 1)})
        self.assertEqual((status, error["code"]), (413, "PAYLOAD_TOO_LARGE"))


if __name__ == "__main__":
    unittest.main()
