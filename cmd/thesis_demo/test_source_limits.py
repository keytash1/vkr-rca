"""Source protocol mistakes must not become observations or credential leaks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import unittest
from unittest.mock import patch

from live_sources import TelemetrySourceError, _get_json, _prometheus, _source_budget, LiveProfile, _workload_intensity
from live_sources import _endpoint
from urllib.parse import urlsplit
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]


class Source(BaseHTTPRequestHandler):
    redirected_calls = 0
    last_path = ""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).last_path = self.path
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/receiver")
            self.end_headers()
            return
        if self.path.startswith("/receiver"):
            type(self).redirected_calls += 1
        payload = b'{"data": "source-response"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class SourceLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), Source)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=5)

    def test_redirect_is_not_followed_with_credentials(self):
        with patch.dict(os.environ, {"RCA_TEST_TOKEN": "synthetic-test-value"}):
            with self.assertRaises(OSError):
                _get_json(self.url, "/redirect", {}, "RCA_TEST_TOKEN")
        self.assertEqual(Source.redirected_calls, 0)

    def test_total_byte_budget_applies_to_source_responses(self):
        token = _source_budget.set([2])
        try:
            with self.assertRaises(TelemetrySourceError):
                _get_json(self.url, "/payload", {}, None)
        finally:
            _source_budget.reset(token)
        self.assertEqual(_get_json(self.url, "/payload", {}, None)["data"], "source-response")

    def test_source_base_url_preserves_a_reverse_proxy_path_prefix(self):
        base = _endpoint(self.url + "/monitoring/prometheus/")
        _get_json(base, "/payload", {}, None)
        self.assertEqual(urlsplit(Source.last_path).path, "/monitoring/prometheus/payload")
        with self.assertRaises(ValueError):
            _endpoint(self.url + "/?token=not-a-supported-credential-location")

    def test_malformed_prometheus_is_a_source_failure_not_a_client_error(self):
        profile = LiveProfile.load(ROOT / "deploy/profiles/lab-system.json", ROOT)
        for value in ({"status": "success", "data": None},
                      {"status": "success", "data": {"resultType": "matrix", "result": [None]}}):
            with self.subTest(value=value), patch("live_sources._get_json", return_value=value):
                with self.assertRaises(TelemetrySourceError):
                    _prometheus(profile, "cpu", 100, 200)

    def test_connect_timeout_remains_a_timeout(self):
        with patch("live_sources.build_opener") as opener:
            opener.return_value.open.side_effect = URLError(TimeoutError("synthetic timeout"))
            with self.assertRaises(TimeoutError):
                _get_json(self.url, "/payload", {}, None)

    def test_invalid_workload_is_a_source_error_not_a_bad_user_request(self):
        self.assertEqual(_workload_intensity([{"values": [[100, "2"], [101, "4"]]}], 100, 101), 3.)
        for invalid in ([], [{"values": []}], [{"values": [[100, "0"]]}],
                        [{"values": [[100, "-1"]]}], [{"values": [[100, "NaN"]]}],
                        [{"values": [[100]]}], [{"values": [[100, "2"], [100, "3"]]}]):
            with self.subTest(invalid=invalid), self.assertRaises(TelemetrySourceError):
                _workload_intensity(invalid, 100, 101)
