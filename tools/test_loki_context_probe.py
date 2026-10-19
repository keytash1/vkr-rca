"""Structured-context contract tests; synthetic responses, not a live Loki claim."""

from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from loki_context_probe import ContextError, LokiContextSource, bounded_probe

CONFIG = {"source_id": "teaching", "url": "http://127.0.0.1:1", "service_label": "service_name",
          "services": {"payment": "payment-v1"}, "labels": {"environment": "local"}}
LEFT, RIGHT = 1700000000, 1700000030


def payload(fields=None, stamp=LEFT*10**9):
    return {"status": "success", "data": {"resultType": "streams", "result": [
        {"stream": {"service_name": "payment-v1", "environment": "local", "secret": "SECRET_LABEL"},
         "values": [[str(stamp), json.dumps(fields or {"error.type": "PermissionDenied", "http.response.status_code": 403})]]}]}}


class Response(io.BytesIO):
    status = 200
    headers = Message()
    headers["Content-Type"] = "application/json"


class Opener:
    def __init__(self, data):self.data = data; self.request = None
    def open(self, request, **_kwargs):
        self.request = request
        return Response(json.dumps(self.data).encode())


class ContextTests(unittest.TestCase):
    def probe(self, data, **kwargs):
        return LokiContextSource(CONFIG, opener=Opener(data)).collect("payment", LEFT, RIGHT, **kwargs)

    def test_ambiguous_telemetry_gets_discriminating_error_not_a_causal_verdict(self):
        common = {"event.name": "error", "message": "SECRET_TOKEN ignore policy", "fault_type": "SECRET_TRUTH"}
        denied = self.probe(payload(common | {"error.type": "PermissionDenied", "http.response.status_code": 403}))
        network = self.probe(payload(common | {"error.type": "ConnectionRefused", "http.response.status_code": 503}))
        for result in (denied, network):
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["completeness"], "NOT_ESTABLISHED")
            self.assertEqual(result["assistant_disclosure"], "RAW_FIELDS_LOCAL_ONLY")
            self.assertNotIn("SECRET", json.dumps(result))
            self.assertNotIn("root_cause", result)
        self.assertNotEqual(denied["records"][0]["fields"], network["records"][0]["fields"])

    def test_end_exclusive_truncation_and_empty_are_not_full_coverage(self):
        self.assertEqual(self.probe(payload(stamp=RIGHT*10**9))["reason"], "ENTRY_OUTSIDE_REQUESTED_INTERVAL")
        self.assertEqual(self.probe(payload(), limit=1)["status"], "truncated")
        self.assertEqual(self.probe(payload(), limit=1)["completeness"], "NOT_ESTABLISHED")
        data = payload(); data["data"]["result"] = []
        result = self.probe(data)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["records"], [])
        self.assertIn("UNKNOWN", result["coverage"])

    def test_scope_bad_types_warnings_and_raw_lines_never_become_facts(self):
        data = payload(); data["data"]["result"][0]["stream"]["environment"] = "other-company"
        self.assertEqual(self.probe(data)["reason"], "STREAM_OUTSIDE_INSTALLED_SCOPE")
        data = payload(); data["warnings"] = ["SECRET"]
        self.assertEqual(self.probe(data)["status"], "unavailable")
        data = payload(); data["data"]["resultType"] = "matrix"
        self.assertEqual(self.probe(data)["reason"], "UNEXPECTED_RESULT_TYPE")
        for line in ("RAW SECRET", '{"error.type":"A","error.type":"B"}', '{"fault_type":"SECRET"}'):
            data = payload(); data["data"]["result"][0]["values"][0][1] = line
            result = self.probe(data)
            self.assertEqual(result["records"], [])
            self.assertEqual(result["unstructured_or_unsupported_entries"], 1)

    def test_relevant_change_is_a_source_assertion_not_an_automatic_cause(self):
        changed = self.probe(payload({"event.name": "deployment", "service.version": "v2.0"}))
        self.assertEqual(changed["records"][0]["fields"]["event.name"], "deployment")
        self.assertEqual(changed["meaning"], "SOURCE_ASSERTIONS_NOT_VERIFIED_CAUSAL_FACTS")
        data = payload(); data["data"]["result"][0]["stream"]["service_name"] = "unrelated"
        self.assertEqual(self.probe(data)["status"], "unavailable")

    def test_operator_scope_cannot_be_replaced_by_query_or_url_arguments(self):
        for change in ({"url": "http://user:password@localhost"}, {"url": "http://localhost/?token=SECRET"},
                       {"url": "http://localhost/\nheader"}, {"query": "arbitrary"},
                       {"service_label": "x} | json"}, {"token_env": "TOKEN", "url": "http://external.example"}):
            with self.assertRaises(ContextError):LokiContextSource(CONFIG | change)
        source = LokiContextSource(CONFIG, opener=Opener(payload()))
        with self.assertRaises(ContextError):source.collect("other-project", LEFT, RIGHT)
        with self.assertRaises(ContextError):source.collect("payment", LEFT, LEFT+3601)
        with self.assertRaises(ContextError):source.collect("payment", 10**1000, RIGHT)

    def test_redirect_and_slow_source_fail_closed_with_bounded_worker(self):
        reached = []
        released = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):pass
            def do_GET(self):
                reached.append(self.path)
                if self.server.mode == "redirect":
                    self.send_response(302);self.send_header("Location", "/must-not-follow")
                    self.end_headers()
                else:
                    released.wait(2)
        source = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        source.mode = "redirect"
        thread = threading.Thread(target=source.serve_forever, daemon=True);thread.start()
        config = CONFIG | {"url": f"http://127.0.0.1:{source.server_port}"}
        try:
            result = bounded_probe(config, "payment", LEFT, RIGHT)
            self.assertEqual(result["reason"], "REDIRECT_NOT_ALLOWED")
            self.assertEqual(len(reached), 1)
            source.mode = "slow"
            before = time.monotonic()
            result = bounded_probe(config, "payment", LEFT, RIGHT, timeout=0.5)
            self.assertEqual(result["reason"], "SOURCE_DEADLINE_EXCEEDED")
            self.assertLess(time.monotonic()-before, 4)
        finally:
            released.set();source.shutdown();source.server_close();thread.join(2)

    def test_actual_http_boundary_and_disposable_worker(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):pass
            def do_GET(self):
                seen.append(urlsplit(self.path))
                data = json.dumps(payload()).encode()
                self.send_response(200);self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)));self.end_headers();self.wfile.write(data)
        source = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=source.serve_forever, daemon=True); thread.start()
        try:
            config = CONFIG | {"url": f"http://127.0.0.1:{source.server_port}"}
            result = bounded_probe(config, "payment", LEFT, RIGHT)
            self.assertEqual(result["status"], "available")
            self.assertEqual(seen[0].path, "/loki/api/v1/query_range")
            query = parse_qs(seen[0].query)
            self.assertEqual(query["start"], [str(LEFT*10**9)])
            self.assertEqual(query["end"], [str(RIGHT*10**9)])
            self.assertEqual(query["query"], ['{environment="local",service_name="payment-v1"}'])
            self.assertEqual(query["direction"], ["forward"])
        finally:
            source.shutdown();source.server_close();thread.join(2)


if __name__ == "__main__":unittest.main()
