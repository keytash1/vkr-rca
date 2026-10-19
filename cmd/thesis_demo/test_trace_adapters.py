"""The new wire adapter must not modify the frozen feature implementation."""

import copy
import json
import unittest
from unittest.mock import patch

from rca_ml.m13_trace import canonicalize_jaeger
from trace_adapters import (
    TraceAccumulator,
    TraceAdapterError,
    decode_v3_stream,
    validate_canonical_spans,
    v3_query,
)


TRACE = "0123456789abcdef0123456789abcdef"
ROOT = "0123456789abcdef"
CHILD = "1123456789abcdef"


def span(identifier=ROOT, **extra):
    return dict(
        traceId=TRACE,
        spanId=identifier,
        startTimeUnixNano="1700000000000000123",
        endTimeUnixNano="1700000000001234999",
        kind=2,
        **extra,
    )


def frame(service="gateway", spans=None):
    return {
        "result": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": service}},
                            {
                                "key": "secret.unneeded",
                                "value": {"stringValue": "not-forwarded"},
                            },
                        ]
                    },
                    "scopeSpans": [{"spans": spans if spans is not None else [span()]}],
                }
            ]
        }
    }


def encoded(*frames):
    return b"\n".join(json.dumps(f).encode() for f in frames)


class AdapterTests(unittest.TestCase):
    def test_http_json_stable_otel_status_reaches_frozen_canonicalizer(self):
        raw = decode_v3_stream(encoded(frame()))[0]
        original = copy.deepcopy(raw)
        scenarios = [
            ([{"key": "http.response.status_code", "value": 503}], True),
            ([{"key": "http.response.status_code", "value": "200"}], False),
            ([{"key": "otel.status_code", "value": "ERROR"}], True),
            ([{"key": "otel.status_code", "value": "OK"}], False),
            ([{"key": "http.response.status_code", "value": 200},
              {"key": "otel.status_code", "value": "ERROR"}], True),
            ([{"key": "error", "value": True}, {"key": "otel.status_code", "value": "OK"}], True),
        ]
        for tags, expected in scenarios:
            item = copy.deepcopy(raw)
            item["spans"][0]["tags"] = tags + [{"key": "private.secret", "value": "discard-me"}]
            accumulator = TraceAccumulator()
            accumulator.add(item)
            canonical = canonicalize_jaeger({"data": accumulator.data()})
            self.assertIs(canonical[0]["error"], expected)
            self.assertNotIn("discard-me", json.dumps(accumulator.data()))
        self.assertEqual(raw, original)

    def test_http_json_legacy_and_stable_aliases_merge_equally(self):
        raw = decode_v3_stream(encoded(frame()))[0]
        first, second = copy.deepcopy(raw), copy.deepcopy(raw)
        first["spans"][0]["tags"] = [{"key": "http.status_code", "value": 503}]
        second["spans"][0]["tags"] = [{"key": "http.response.status_code", "value": "503"}]
        accumulator = TraceAccumulator()
        accumulator.add(first)
        accumulator.add(second)
        self.assertEqual(len(accumulator.data()[0]["spans"]), 1)
        self.assertTrue(canonicalize_jaeger({"data": accumulator.data()})[0]["error"])

    def test_typed_zipkin_error_message_is_error_not_forwarded_or_conflict(self):
        for message in ("Chaos Monkey - RuntimeException", "", "false"):
            raw = decode_v3_stream(encoded(frame()))[0]
            raw["spans"][0]["tags"] = [
                {"key": "error", "type": "string", "value": message},
                {"key": "error", "type": "bool", "value": True},
                {"key": "otel.status_code", "type": "string", "value": "ERROR"}]
            accumulator = TraceAccumulator()
            accumulator.add(raw)
            self.assertTrue(canonicalize_jaeger({"data": accumulator.data()})[0]["error"])
            self.assertEqual(accumulator.data()[0]["spans"][0]["tags"], [{"key": "error", "value": True}])
            otlp = frame(spans=[span(attributes=[{"key": "error", "value": {"stringValue": message}}])])
            self.assertTrue(canonicalize_jaeger({"data": decode_v3_stream(encoded(otlp))})[0]["error"])
        false = frame(spans=[span(attributes=[{"key": "error", "value": {"boolValue": False}}])])
        self.assertFalse(canonicalize_jaeger({"data": decode_v3_stream(encoded(false))})[0]["error"])

    def test_http_json_stable_status_invalid_or_conflicting_is_not_normal(self):
        scenarios = [[{"key": "http.response.status_code", "value": value}] for value in
                     (True, None, 0, 600, 503., "NaN")]
        scenarios.append([{"key": "http.response.status_code", "value": 200}, {"key": "http.status_code", "value": 503}])
        scenarios.extend([[{"key": "otel.status_code", "value": v}] for v in (True, 2, "broken")])
        for tags in scenarios:
            raw = decode_v3_stream(encoded(frame()))[0]
            raw["spans"][0]["tags"] = tags
            with self.subTest(tags=tags), self.assertRaises(TraceAdapterError):
                TraceAccumulator().add(raw)

    def test_only_exact_pinned_v3_empty_search_404_is_no_results(self):
        import io
        from urllib.error import HTTPError
        from live_sources import _get_payload
        from trace_adapters import is_v3_no_matches
        empty = b'{"error":{"httpCode":404,"message":"No traces found"}}'
        self.assertTrue(is_v3_no_matches(empty))
        for body in (b'not found',b'<html>404</html>',b'{"error":{"httpCode":404,"message":"unknown endpoint"}}',
                     b'{"error":{"httpCode":404,"message":"secret","message":"No traces found"}}'):
            self.assertFalse(is_v3_no_matches(body))
        for flag, body, accepted in ((True,empty,True),(False,empty,False),(True,b'not found',False)):
            error = HTTPError('http://127.0.0.1/api/v3/traces',404,'not found',{},io.BytesIO(body))
            with patch('live_sources.build_opener') as opener:
                opener.return_value.open.side_effect=error
                if accepted:
                    payload=_get_payload('http://127.0.0.1','/api/v3/traces',{},None,v3_empty_search=flag)
                    self.assertEqual(decode_v3_stream(payload),[])
                else:
                    with self.assertRaises(OSError):
                        _get_payload('http://127.0.0.1','/api/v3/traces',{},None,v3_empty_search=flag)

    def test_overlapping_partial_searches_are_merged(self):
        first = decode_v3_stream(encoded(frame()))[0]
        second = decode_v3_stream(
            encoded(frame("orders", [span(CHILD, parentSpanId=ROOT)]))
        )[0]
        accumulator = TraceAccumulator()
        accumulator.add(first)
        accumulator.add(second)
        accumulator.add(first)
        canonical = canonicalize_jaeger({"data": accumulator.data()})
        self.assertEqual(len(canonical), 2)
        self.assertEqual(
            canonical[1]["observed_edge"], {"source": "gateway", "target": "orders"}
        )
        damaged = copy.deepcopy(first)
        damaged["spans"][0]["duration"] += 1
        with self.assertRaisesRegex(TraceAdapterError, "CONFLICTING_SPAN"):
            accumulator.add(damaged)

    def test_resources_chunks_parent_and_nanosecond_precision(self):
        child = span(
            CHILD,
            parentSpanId=ROOT,
            attributes=[
                {"key": "http.response.status_code", "value": {"intValue": "503"}}
            ],
        )
        traces = decode_v3_stream(encoded(frame(), frame("orders", [child])))
        self.assertEqual(len(traces), 1)
        canonical = validate_canonical_spans(canonicalize_jaeger({"data": traces}))
        self.assertEqual(len(canonical), 2)
        one, two = canonical
        self.assertEqual(one["start_time_us"], 1700000000000000)
        self.assertEqual(one["duration_us"], 1234)
        self.assertEqual(two["parent_span_id"], ROOT)
        self.assertEqual(
            two["observed_edge"], {"source": "gateway", "target": "orders"}
        )
        self.assertTrue(two["error"])
        self.assertNotIn("secret.unneeded", json.dumps(traces))

    def test_enum_kind_status_zero_parent_and_case(self):
        raw = span(parentSpanId="0" * 16, status={"code": "STATUS_CODE_ERROR"})
        raw["kind"] = "SPAN_KIND_CLIENT"
        raw["traceId"] = TRACE.upper()
        converted = canonicalize_jaeger(
            {"data": decode_v3_stream(encoded(frame(spans=[raw])))}
        )[0]
        self.assertEqual(converted["span_kind"], "CLIENT")
        self.assertEqual(converted["trace_id"], TRACE)
        self.assertEqual(converted["parent_span_id"], "")
        self.assertTrue(converted["error"])

    def test_duplicate_is_idempotent_but_conflict_is_error(self):
        self.assertEqual(
            len(decode_v3_stream(encoded(frame(), frame()))[0]["spans"]), 1
        )
        other = frame()
        other["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0][
            "endTimeUnixNano"
        ] = "1700000000990000000"
        with self.assertRaisesRegex(TraceAdapterError, "CONFLICTING_SPAN"):
            decode_v3_stream(encoded(frame(), other))

    def test_invalid_stream_never_becomes_partial_success(self):
        for tail in [
            b'{"error":{"message":"failed"}}',
            b'{"result":{},"result":{}}',
            b'{"result":{"x":NaN}}',
            b'{"result":',
            b"[]",
            b"\xff",
        ]:
            with self.subTest(tail=tail), self.assertRaises(TraceAdapterError):
                decode_v3_stream(encoded(frame()) + b"\n" + tail)

    def test_empty_result(self):
        self.assertEqual(decode_v3_stream(b'{"result":{}}\n'), [])
        for empty in (b'', b' \n\t'):
            with self.assertRaisesRegex(TraceAdapterError, "STREAM_EMPTY"):
                decode_v3_stream(empty)

    def test_legacy_false_string_is_not_an_observed_error(self):
        raw = decode_v3_stream(encoded(frame()))[0]
        raw['spans'][0]['tags'] = [{'key':'error','value':'false'}]
        with self.assertRaisesRegex(TraceAdapterError, "ERROR_TYPE_INVALID"):
            TraceAccumulator().add(raw)

    def test_invalid_spans(self):
        changes = [
            dict(traceId="0" * 32),
            dict(spanId="broken"),
            dict(kind=True),
            dict(startTimeUnixNano="NaN"),
            dict(endTimeUnixNano="1"),
            dict(status={"code": False}),
            dict(startTimeUnixNano=2**64),
            dict(attributes=[{"key": "error", "value": {"intValue": "1"}}]),
        ]
        for change in changes:
            raw = span()
            raw.update(change)
            with self.subTest(change=change), self.assertRaises(TraceAdapterError):
                decode_v3_stream(encoded(frame(spans=[raw])))

    def test_budget_before_unbounded_materialization(self):
        with (
            patch("trace_adapters.MAX_CANONICAL_SPANS", 1),
            self.assertRaises(TraceAdapterError),
        ):
            decode_v3_stream(encoded(frame(spans=[span(), span(CHILD)])))
        with (
            patch("trace_adapters.MAX_SPANS_PER_TRACE", 1),
            self.assertRaises(TraceAdapterError),
        ):
            decode_v3_stream(encoded(frame(spans=[span(), span(CHILD)])))

    def test_exclusive_source_boundary_preserves_inclusive_microsecond(self):
        query = v3_query("orders", 1700000000, 1700000001, 1000)
        self.assertEqual(query["query.startTimeMin"], "2023-11-14T22:13:20.000000Z")
        self.assertEqual(query["query.startTimeMax"], "2023-11-14T22:13:21.000001Z")
        self.assertEqual(query["query.rawTraces"], "true")

    def test_cycle_duplicate_and_nonfinite_rejected_partial_parent_allowed(self):
        good = canonicalize_jaeger({"data": decode_v3_stream(encoded(frame()))})
        partial = copy.deepcopy(good)
        partial[0]["parent_span_id"] = CHILD
        self.assertEqual(validate_canonical_spans(partial), partial)
        bad = copy.deepcopy(good)
        bad[0]["parent_span_id"] = ROOT
        for value in [bad, good + good, [good[0] | {"duration_us": float("nan")}]]:
            with self.subTest(value=value), self.assertRaises(TraceAdapterError):
                validate_canonical_spans(value)
        other = good[0] | {"span_id": CHILD, "parent_span_id": ROOT}
        with self.assertRaisesRegex(TraceAdapterError, "PARENT_CYCLE"):
            validate_canonical_spans([good[0] | {"parent_span_id": CHILD}, other])


if __name__ == "__main__":
    unittest.main()
