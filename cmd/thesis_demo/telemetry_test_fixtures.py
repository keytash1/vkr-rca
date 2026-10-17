"""Synthetic local Prometheus/legacy Jaeger HTTP responses, never real data."""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

class FakeTelemetry(BaseHTTPRequestHandler):
    fail_metrics = False
    fail_traces = False
    duplicate_metrics = False
    warn_metrics = False
    missing_network = False
    nonfinite_cpu = False
    disconnected_traces = False

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
            if self.warn_metrics:
                payload["warnings"] = ["source returned partial query data"]
            if self.missing_network and query == "network":
                payload["data"]["result"] = []
            if self.nonfinite_cpu and query == "cpu":
                payload["data"]["result"][0]["values"][0][1] = "NaN"
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
            if self.disconnected_traces and args["service"][0] == "ad":
                payload["data"][0]["traceID"] = "isolated-ad"
                payload["data"][0]["processes"]["p1"]["serviceName"] = "ad"
                payload["data"][0]["spans"][0]["traceID"] = "isolated-ad"
        else:
            self.send_error(404)
            return
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
