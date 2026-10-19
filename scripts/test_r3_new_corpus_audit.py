"""Small source-boundary checks; no model, source download or GPU required."""
import io
import json
import unittest
from unittest.mock import patch

from r3_new_corpus_audit import get, metric_identity_counts, select_cases, TABLES


class Response(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {} if length is None else {"Content-Length": str(length)}


class AuditBoundaryTests(unittest.TestCase):
    def test_truth_and_order_do_not_influence_selection(self):
        rows = [{"name": f"case-{s}-{i}", "system": s, "root_services": ["oracle"]}
                for s in ("hs", "otel-demo", "ts") for i in range(4)]
        raw = lambda rs: b"\n".join(json.dumps(r).encode() for r in rs)
        before = select_cases(raw(rows))[1]
        altered = [dict(r, root_services=["other"], chaos_types=["other"]) for r in reversed(rows)]
        self.assertEqual(before, select_cases(raw(altered))[1])
        self.assertTrue(all(set(r) == {"name", "system"} for r in before))
        self.assertEqual(len(TABLES), 10)
        self.assertFalse(any(k in name for name in TABLES for k in ("label", "injection", "env", "causal")))

    def test_unknown_system_and_path_traversal_rejected(self):
        rows = [{"name": s, "system": s} for s in ("hs", "otel-demo", "ts")]
        for bad in (dict(rows[0], system="unknown"), dict(rows[0], name="../x")):
            payload = b"\n".join(json.dumps(r).encode() for r in [bad, *rows[1:]])
            with self.assertRaises(ValueError):
                select_cases(payload)

    def test_conflicts_are_not_silently_deduplicated_or_summed(self):
        a = {"time_ns": 1, "metric": "counter", "service_name": "a", "value": 2}
        rows = [a, dict(a), dict(a, value=3), dict(a, service_name="b"), dict(a, time_ns=2)]
        self.assertEqual(metric_identity_counts(rows), {
            "duplicate_identity_groups": 1, "conflicting_identity_groups": 1,
            "rows_in_conflicting_groups": 3})
        self.assertEqual(rows[2]["value"], 3)
        self.assertEqual(metric_identity_counts([a, dict(a)])["conflicting_identity_groups"], 0)

    def test_download_bound_checks_header_and_actual_stream(self):
        for response in (Response(b"12345", 5), Response(b"12345")):
            with patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(ValueError):
                    get("https://example.invalid", 4)
        with patch("urllib.request.urlopen", return_value=Response(b"1234", 4)):
            self.assertEqual(get("https://example.invalid", 4), b"1234")


if __name__ == "__main__":
    unittest.main()
