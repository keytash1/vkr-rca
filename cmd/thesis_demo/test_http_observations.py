"""HTTP facts are bounded supplemental evidence, never replacement ML input."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from http_observations import (CHANNELS, VERSION, attach_http, collect_http,
                               decode_matrix, digest, summarize, validate_config)

SERVICES = ("alpha", "beta")
CONFIG = {"version": VERSION, "source_presence_query": "presence", "lookback_seconds": 30,
          "queries": {c: {"query": c, "unit": unit, "statistic": statistic}
                      for c, (unit, statistic) in CHANNELS.items()}}
SCOPE = {"services": SERVICES, "aliases": {}, "ignored": (), "label": "service"}


def matrix(channel, changes=None):
    default = {"presence": 1., "request_rate": 5., "error_ratio": .25, "latency_p95": .1}[channel]
    return {"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": {"service": s, "secret.label": "NOT_FORWARDED"},
         "values": [[t, str((changes or {}).get(s, {}).get(t, default))] for t in (100, 101, 102)]}
        for s in SERVICES]}}


def decoded(changes=None):
    return {c: decode_matrix(matrix(c, (changes or {}).get(c)), SCOPE, c, 100, 102)
            for c in (*CHANNELS, "presence")}


def profile(url="http://127.0.0.1:1"):
    return SimpleNamespace(http_observations_config=copy.deepcopy(CONFIG), services=SERVICES,
        aliases={}, ignored_service_labels=frozenset(), metric_service_label="service",
        metrics_url=url, metric_token_env=None, query_step_seconds=1)


class HTTPContractTests(unittest.TestCase):
    def test_optional_configuration_does_not_change_healthy_contract(self):
        from live_sources import LiveProfile
        from profile_contract import contract_sha256
        from profile_test_fixtures import profile_document
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "profile.json"
            raw = profile_document()
            path.write_text(json.dumps(raw))
            previous = LiveProfile.load(path, root, require_artifacts=False)
            raw["http_observations"] = copy.deepcopy(CONFIG)
            path.write_text(json.dumps(raw))
            current = LiveProfile.load(path, root, require_artifacts=False)
            self.assertEqual(current.http_observations_config, CONFIG)
            self.assertEqual(contract_sha256(current), contract_sha256(previous))

    def test_units_statistics_and_configuration_are_explicit(self):
        self.assertEqual(validate_config(CONFIG), CONFIG)
        for mutate in (lambda c: c["queries"]["latency_p95"].update(unit="milliseconds"),
                       lambda c: c["queries"]["error_ratio"].update(statistic="count"),
                       lambda c: c.update(url="http://attacker.invalid"),
                       lambda c: c.update(source_presence_query="")):
            bad = copy.deepcopy(CONFIG)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_config(bad)

    def test_observed_values_are_not_baseline_or_model_features(self):
        result = summarize(decoded(), SERVICES, 100, 102, 1)
        self.assertEqual(result["status"], "complete")
        values = result["services"]["alpha"]["metrics"]["error_ratio"]
        self.assertEqual(values["median"], .25)
        self.assertEqual(values["unit"], "ratio")
        self.assertFalse(values["model_input"])
        self.assertIsNone(values["baseline_comparison"])
        self.assertNotIn("NOT_FORWARDED", json.dumps(result))

    def test_idle_and_source_outage_are_not_normal_zero(self):
        idle = {"request_rate": {s: dict.fromkeys((100, 101, 102), 0.) for s in SERVICES},
                "error_ratio": {s: dict.fromkeys((100, 101, 102), float("nan")) for s in SERVICES},
                "latency_p95": {s: dict.fromkeys((100, 101, 102), float("nan")) for s in SERVICES}}
        result = summarize(decoded(idle), SERVICES, 100, 102, 1)
        self.assertEqual(result["services"]["alpha"]["state"], "NO_ACTIVITY")
        self.assertEqual(result["services"]["alpha"]["metrics"]["request_rate"]["median"], 0)
        self.assertEqual(result["services"]["alpha"]["metrics"]["latency_p95"]["state"], "NOT_DEFINED_WITHOUT_TRAFFIC")
        idle["presence"] = {"alpha": {102: 0}}
        down = summarize(decoded(idle), SERVICES, 100, 102, 1)["services"]["alpha"]
        self.assertEqual(down["state"], "UNAVAILABLE")
        self.assertIsNone(down["metrics"]["request_rate"]["median"])
        self.assertEqual(down["metrics"]["request_rate"]["samples"], 0)

    def test_partial_and_mixed_activity_keep_undefined_distinct(self):
        changes = {"request_rate": {"alpha": {101: 0., 102: 0.}}}
        result = summarize(decoded(changes), SERVICES, 100, 102, 1)
        value = result["services"]["alpha"]["metrics"]["error_ratio"]
        self.assertEqual(value["samples"], 1)
        self.assertEqual(value["median"], .25)
        missing = decoded()
        del missing["latency_p95"]["alpha"][101]
        self.assertEqual(summarize(missing, SERVICES, 100, 102, 1)["services"]["alpha"]["state"], "PARTIAL")
        missing["request_rate"]["alpha"] = {}
        self.assertEqual(summarize(missing, SERVICES, 100, 102, 1)["services"]["alpha"]["state"], "INCOMPLETE")

    def test_semantic_and_aggregation_errors_rejected(self):
        for value in ("-1", "1.1", "Inf", "-Inf", True):
            raw = matrix("error_ratio")
            raw["data"]["result"][0]["values"][0][1] = value
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                decode_matrix(raw, SCOPE, "error_ratio", 100, 102)
        for mutate in (lambda p: p["data"]["result"].append(copy.deepcopy(p["data"]["result"][0])),
                       lambda p: p["data"]["result"][0]["metric"].update(service="foreign"),
                       lambda p: p["data"]["result"][0]["values"].append([100, "1"]),
                       lambda p: p.update(warnings=["SECRET_SOURCE_TEXT"])):
            raw = matrix("presence")
            mutate(raw)
            with self.assertRaises(ValueError):
                decode_matrix(raw, SCOPE, "presence", 100, 102)

    def test_aliases_cannot_create_duplicate_candidates(self):
        raw = matrix("presence")
        raw["data"]["result"][1]["metric"]["service"] = "alias-alpha"
        with self.assertRaises(ValueError):
            decode_matrix(raw, SCOPE | {"aliases": {"alias-alpha": "alpha"}}, "presence", 100, 102)

    def test_shifted_query_grid_cannot_claim_complete_coverage(self):
        data = decoded()
        data['presence']['alpha'] = {100.1:1, 101.1:1, 101.9:1}
        with self.assertRaises(ValueError):
            summarize(data, SERVICES, 100, 102, 1)

    def test_attachment_preserves_core_and_stable_ids(self):
        from test_evidence_catalog import fixture
        from evidence_catalog import build_catalog
        from assistant_context import assistant_context
        window, analysis, baseline = fixture()
        window["end_unix"] = analysis["end_unix"] = 102
        original = build_catalog(window, analysis, baseline)
        before = copy.deepcopy(original)
        result = summarize(decoded(), SERVICES, 100, 102, 1)
        result["config_sha256"] = digest(CONFIG)
        current = attach_http(original, profile(), result)
        self.assertEqual(original, before)
        self.assertEqual(current["observations"][:len(original["observations"])], original["observations"])
        for key in ("input_sha256", "baseline_sha256", "feature_schema_sha256", "model_version"):
            self.assertEqual(current[key], original[key])
        self.assertEqual(current, attach_http(original, profile(), result))
        self.assertNotIn("presence", json.dumps(assistant_context(current)))
        with self.assertRaises(ValueError):
            attach_http(original, profile(), dict(result, end_unix=103))


class HTTPWorkerTests(unittest.TestCase):
    def source(self, mode="normal"):
        calls, stop = [], threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.path, self.headers.get("Authorization")))
                if mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/must-not-follow")
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                if mode == "slow":
                    while not stop.wait(.05):
                        try:
                            self.wfile.write(b" ")
                            self.wfile.flush()
                        except OSError:
                            break
                    return
                channel = parse_qs(urlsplit(self.path).query)["query"][0]
                self.wfile.write(json.dumps(matrix(channel)).encode())
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(stop.set)
        return profile(f"http://127.0.0.1:{server.server_port}"), calls

    def test_real_worker_has_four_queries_without_credential_or_label_disclosure(self):
        settings, calls = self.source()
        settings.metric_token_env = "RCA_TEST_HTTP_OBSERVATION_TOKEN"
        with patch.dict(os.environ, {settings.metric_token_env: "SYNTHETIC_TEST_TOKEN"}):
            result = collect_http(settings, 100, 102)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(token == "Bearer SYNTHETIC_TEST_TOKEN" for _, token in calls))
        self.assertNotIn("SYNTHETIC_TEST_TOKEN", json.dumps(result))
        self.assertNotIn("NOT_FORWARDED", json.dumps(result))

    def test_redirect_never_forwards_credentials(self):
        settings, calls = self.source("redirect")
        result = collect_http(settings, 100, 102)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("must-not-follow", json.dumps(result))

    def test_slow_drip_has_global_deadline_and_no_worker_left(self):
        settings, _ = self.source("slow")
        before = {p.pid for p in multiprocessing.active_children()}
        began = time.monotonic()
        result = collect_http(settings, 100, 102, timeout=1)
        self.assertLess(time.monotonic()-began, 2)
        self.assertEqual(result["reason"], "HTTP_SOURCE_DEADLINE_EXCEEDED")
        self.assertTrue({p.pid for p in multiprocessing.active_children()} <= before)


if __name__ == "__main__":
    unittest.main()
