"""HTTP end-to-end tests for the profile -> sources -> model -> response path."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import DiagnosticApplication, make_handler
from live_sources import TRACE_LIMIT, TelemetrySourceError, _jaeger_interval, _remaining


ROOT = Path(__file__).resolve().parents[2]


class FakeTelemetry(BaseHTTPRequestHandler):
    fail_metrics = False
    fail_traces = False
    duplicate_metrics = False

    def log_message(self, *_args):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        args = parse_qs(parsed.query)
        if parsed.path == "/api/v1/query_range":
            if self.fail_metrics:
                self.send_error(503)
                return
            query = args["query"][0]
            if query not in {"cpu", "memory", "network", "traffic_rate"}:
                self.send_error(400)
                return
            timestamp = (float(args["start"][0]) + float(args["end"][0])) / 2
            value = 1.0 if query != "memory" else 100_000_000.0
            payload = {"status": "success", "data": {"resultType": "matrix", "result": [
                {"metric": {"service": "frontend"}, "values": [[timestamp, str(value)]]}
            ]}}
            if self.duplicate_metrics:
                payload["data"]["result"].append(payload["data"]["result"][0])
        elif parsed.path == "/api/traces":
            if self.fail_traces:
                self.send_error(503)
                return
            timestamp = int(args["start"][0]) + 1_000_000
            payload = {"data": [{
                "traceID": "test-trace", "processes": {"p1": {"serviceName": "frontend"}},
                "spans": [{"traceID": "test-trace", "spanID": "s1", "processID": "p1",
                           "startTime": timestamp, "duration": 10_000,
                           "tags": [{"key": "span.kind", "value": "SERVER"}],
                           "references": []}],
            }]}
        else:
            self.send_error(404)
            return
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LivePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelemetry)
        cls.source_thread = threading.Thread(target=cls.source.serve_forever, daemon=True)
        cls.source_thread.start()
        cls.temp = tempfile.TemporaryDirectory()
        profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
        url = f"http://127.0.0.1:{cls.source.server_port}"
        profile["metrics"]["url"] = url
        profile["metrics"]["queries"] = {family: family for family in profile["metrics"]["queries"]}
        profile["traces"]["url"] = url
        path = Path(cls.temp.name) / "test.json"
        path.write_text(json.dumps(profile))
        cls.app = DiagnosticApplication(ROOT, Path(cls.temp.name))
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=5)
        cls.source.shutdown()
        cls.source.server_close()
        cls.source_thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)

    def test_profile_interval_to_ranking(self):
        status, profiles = self.request("/api/profiles")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in profiles], ["lab-system"])
        status, result = self.request("/api/analyze", {
            "profile_id": "lab-system", "start_unix": 1_700_000_000, "end_unix": 1_700_000_030,
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["candidate_count"], 12)
        self.assertEqual(result["source_status"]["metrics"], "available")
        self.assertEqual(result["source_status"]["traces"], "available")
        self.assertEqual(result["source_status"]["metric_families_by_service"]["frontend"],
                         ["cpu", "memory", "network", "traffic_rate"])
        self.assertEqual(len(result["candidates"]), 12)
        self.assertNotIn("root_service", result)
        self.assertEqual(result["model_count"], 5)
        frontend = next(item for item in result["candidates"] if item["service"] == "frontend")
        self.assertEqual(frontend["observations"]["metrics"]["cpu"]["samples"], 1)
        self.assertGreater(frontend["observations"]["traces"]["count"], 0)
        absent = next(item for item in result["candidates"] if item["service"] == "ad")
        self.assertEqual(absent["observations"]["metrics"], {})

    def test_trace_failure_is_reported_not_zero_filled(self):
        FakeTelemetry.fail_traces = True
        try:
            _, result = self.request("/api/analyze", {
                "profile_id": "lab-system", "start_unix": 1_700_000_100, "end_unix": 1_700_000_130,
            })
            self.assertEqual(result["source_status"]["traces"], "unavailable")
            self.assertEqual(result["source_status"]["span_count"], 0)
            self.assertEqual(result["candidate_count"], 12)
        finally:
            FakeTelemetry.fail_traces = False

    def test_metric_source_failure_rejects_ranking(self):
        FakeTelemetry.fail_metrics = True
        try:
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/analyze", {
                    "profile_id": "lab-system", "start_unix": 1_700_000_200,
                    "end_unix": 1_700_000_230,
                })
            self.assertEqual(caught.exception.code, 502)
            caught.exception.close()
        finally:
            FakeTelemetry.fail_metrics = False

    def test_duplicate_source_series_rejects_ranking(self):
        FakeTelemetry.duplicate_metrics = True
        try:
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/analyze", {
                    "profile_id": "lab-system", "start_unix": 1_700_000_200,
                    "end_unix": 1_700_000_230,
                })
            self.assertEqual(caught.exception.code, 502)
            caught.exception.close()
        finally:
            FakeTelemetry.duplicate_metrics = False

    def test_saturated_trace_search_is_split(self):
        profile = self.app.profiles["lab-system"]
        calls = []

        def response(_base, _path, params, _token, _timeout):
            calls.append(params)
            if params["end"] - params["start"] > 5_000_000:
                return {"data": [{"traceID": str(i)} for i in range(TRACE_LIMIT)]}
            return {"data": [{"traceID": str(len(calls))}]}

        with patch("live_sources._get_json", side_effect=response):
            traces = _jaeger_interval(profile, "frontend", 0, 10, [10])
        self.assertEqual(len(traces), 2)
        self.assertEqual(len(calls), 3)

    def test_collection_deadline_is_bounded(self):
        with self.assertRaises(TelemetrySourceError):
            _remaining(0)

    def test_product_installation_does_not_need_experiment_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("m10c-v2", "m10d-integration", "m11", "m12", "m13"):
                shutil.copytree(ROOT / "ml/models" / name, root / "ml/models" / name)
            artifact_dir = root / "deploy/profiles/artifacts/portable"
            artifact_dir.mkdir(parents=True)
            for name in ("healthy-baseline.json", "legacy-metric-baseline.json"):
                shutil.copyfile(ROOT / "ml/models/m14" / name, artifact_dir / name)
            profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
            profile["id"] = "portable"
            profile["artifact_dir"] = "deploy/profiles/artifacts/portable"
            profile["metrics"]["url"] = f"http://127.0.0.1:{self.source.server_port}"
            profile["metrics"]["queries"] = {family: family for family in profile["metrics"]["queries"]}
            profile["traces"]["url"] = profile["metrics"]["url"]
            (root / "deploy/profiles/portable.json").write_text(json.dumps(profile))
            app = DiagnosticApplication(root)
            self.assertIsNone(app.runtime)
            self.assertIsNone(app.evaluation)
            self.assertFalse(app.examples)
            result = app.analyze_live("portable", 1_700_000_000, 1_700_000_030)
            self.assertEqual(result["candidate_count"], 12)
            self.assertEqual(len(result["candidates"]), 12)


if __name__ == "__main__":
    unittest.main()
