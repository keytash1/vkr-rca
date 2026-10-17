"""Jaeger stable QueryService v3 / OTLP JSON -> existing canonicalizer input.

No new ranking feature or model math. Only known identity/time/kind/error fields
are projected. Raw operation names, tags, links and resource metadata are not
forwarded. Contract: jaeger-idl v0.9.0, tested against Jaeger 2.20.0.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import math

MAX_CANONICAL_SPANS = 50000
MAX_SPANS_PER_TRACE = 2048


class TraceAdapterError(ValueError):
    pass


def is_v3_no_matches(payload):
    """Pinned Jaeger 2.20 QueryService empty-search response, not generic 404.

    Observed on the actual server: text/plain JSON with exactly this error.
    A missing route/HTML/upstream failure is never interpreted as no spans.
    """
    if not isinstance(payload, bytes) or len(payload) > 4096:
        return False
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate error field")
            value[key] = item
        return value
    try:
        value = json.loads(payload, object_pairs_hook=pairs)
        return value == {"error": {"httpCode": 404, "message": "No traces found"}}
    except (ValueError, UnicodeError, RecursionError):
        return False


class TraceAccumulator:
    """Merge overlapping searches, including partial traces, without last-write loss.

    Process IDs are local to one Jaeger response: use service identity when
    combining. Only fields consumed by the existing canonicalizer are retained.
    """

    def __init__(self):
        self.traces = {}
        self.count = 0

    def add(self, trace):
        if not isinstance(trace, dict) or not isinstance(trace.get("traceID"), str):
            raise TraceAdapterError("TRACE_IDENTIFIER_INVALID")
        identifier = trace["traceID"]
        processes, spans = trace.get("processes", {}), trace.get("spans", [])
        if not isinstance(processes, dict) or not isinstance(spans, list):
            raise TraceAdapterError("TRACE_PAYLOAD_INVALID")
        target = self.traces.setdefault(
            identifier, {"traceID": identifier, "processes": {}, "spans": {}}
        )
        for span in spans:
            if (
                not isinstance(span, dict)
                or span.get("traceID") != identifier
                or not isinstance(span.get("spanID"), str)
            ):
                raise TraceAdapterError("TRACE_SPAN_IDENTITY_INVALID")
            process = processes.get(span.get("processID"))
            if (
                not isinstance(process, dict)
                or not isinstance(process.get("serviceName"), str)
                or not process["serviceName"]
            ):
                raise TraceAdapterError("TRACE_SERVICE_IDENTITY_MISSING")
            service = process["serviceName"]
            tags, refs = span.get("tags", []), span.get("references", [])
            if not isinstance(tags, list) or not isinstance(refs, list):
                raise TraceAdapterError("TRACE_SPAN_METADATA_INVALID")
            relevant_tags = {}
            for tag in tags:
                if not isinstance(tag, dict):
                    raise TraceAdapterError("TRACE_SPAN_METADATA_INVALID")
                key = tag.get("key")
                if key in {"span.kind", "error", "status.code", "http.status_code"}:
                    if key == "error" and not isinstance(tag.get("value"), bool):
                        raise TraceAdapterError("TRACE_ERROR_TYPE_INVALID")
                    if key == "span.kind" and (not isinstance(tag.get("value"), str) or len(tag["value"]) > 64):
                        raise TraceAdapterError("TRACE_KIND_INVALID")
                    if key in relevant_tags and relevant_tags[key] != tag.get("value"):
                        raise TraceAdapterError("TRACE_ATTRIBUTE_CONFLICT")
                    relevant_tags[key] = tag.get("value")
            parents = []
            for ref in refs:
                if not isinstance(ref, dict):
                    raise TraceAdapterError("TRACE_REFERENCE_INVALID")
                if ref.get("refType") == "CHILD_OF":
                    if ref.get("traceID", identifier) != identifier:
                        raise TraceAdapterError("TRACE_CROSS_TRACE_PARENT")
                    parents.append(ref.get("spanID"))
            if len(set(parents)) > 1 or any(not isinstance(p, str) for p in parents):
                raise TraceAdapterError("TRACE_MULTIPLE_PARENTS")
            for field in ("startTime", "duration"):
                if isinstance(span.get(field), bool) or not isinstance(span.get(field), int) or span[field] < 0:
                    raise TraceAdapterError("TRACE_INTEGER_INVALID")
            value = {
                "traceID": identifier,
                "spanID": span["spanID"],
                "processID": service,
                "startTime": span.get("startTime"),
                "duration": span.get("duration"),
                "tags": [
                    {"key": k, "value": v} for k, v in sorted(relevant_tags.items())
                ],
                "references": [
                    {"refType": "CHILD_OF", "spanID": parents[0], "traceID": identifier}
                ]
                if parents
                else [],
            }
            old = target["spans"].get(span["spanID"])
            if old is not None and old != value:
                raise TraceAdapterError("TRACE_CONFLICTING_SPAN")
            if old is None:
                self.count += 1
                if (
                    self.count > MAX_CANONICAL_SPANS
                    or len(target["spans"]) >= MAX_SPANS_PER_TRACE
                ):
                    raise TraceAdapterError("TRACE_ACCUMULATION_BUDGET")
            target["spans"][span["spanID"]] = value
            target["processes"][service] = {"serviceName": service}

    def data(self):
        return [
            trace | {"spans": list(trace["spans"].values())}
            for trace in self.traces.values()
        ]


KIND = {
    0: "UNKNOWN",
    1: "INTERNAL",
    2: "SERVER",
    3: "CLIENT",
    4: "PRODUCER",
    5: "CONSUMER",
}


def _uint(value):
    if isinstance(value, bool):
        raise TraceAdapterError("TRACE_INTEGER_INVALID")
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,20}", value):
            raise TraceAdapterError("TRACE_INTEGER_INVALID")
        value = int(value)
    if not isinstance(value, int) or not 0 <= value < 2**64:
        raise TraceAdapterError("TRACE_INTEGER_INVALID")
    return value


def _identifier(value, length, *, parent=False):
    if parent and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{" + str(length) + r"}", value
    ):
        raise TraceAdapterError("TRACE_IDENTIFIER_INVALID")
    if not int(value, 16):
        if parent:
            return ""
        raise TraceAdapterError("TRACE_ZERO_IDENTIFIER")
    return value.lower()


def _attributes(items, wanted):
    if not isinstance(items, list):
        raise TraceAdapterError("TRACE_ATTRIBUTES_INVALID")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise TraceAdapterError("TRACE_ATTRIBUTE_INVALID")
        key = item.get("key")
        if not isinstance(key, str):
            raise TraceAdapterError("TRACE_ATTRIBUTE_KEY_INVALID")
        if key not in wanted:
            continue
        value = item.get("value")
        if not isinstance(value, dict) or len(value) != 1:
            raise TraceAdapterError("TRACE_ATTRIBUTE_VALUE_INVALID")
        # Only scalars used by the contract, not arbitrary AnyValue content.
        field = next(iter(value))
        if field not in {"stringValue", "intValue", "boolValue"}:
            raise TraceAdapterError("TRACE_ATTRIBUTE_TYPE_INVALID")
        scalar = value[field]
        if key in result and result[key] != scalar:
            raise TraceAdapterError("TRACE_ATTRIBUTE_CONFLICT")
        result[key] = scalar
    return result


def v3_query(service, left, right, limit):
    def timestamp(microseconds):
        seconds, fraction = divmod(microseconds, 1_000_000)
        return (
            datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            + f".{fraction:06d}Z"
        )

    # v3's upper bound is exclusive; the frozen canonical contract includes
    # the final microsecond. Do not silently change window boundary semantics.
    return {
        "query.serviceName": service,
        "query.startTimeMin": timestamp(int(left * 1e6)),
        "query.startTimeMax": timestamp(int(right * 1e6) + 1),
        "query.searchDepth": limit,
        "query.rawTraces": "true",
    }


def decode_v3_stream(payload):
    """All-or-error decoding: a late error never becomes a valid partial trace."""
    if not isinstance(payload, bytes) or len(payload) > 32 * 1024 * 1024:
        raise TraceAdapterError("TRACE_RESPONSE_BUDGET")
    traces = {}
    span_count = 0
    envelopes = 0

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TraceAdapterError("TRACE_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    for line in payload.splitlines():
        if not line.strip():
            continue
        envelopes += 1
        try:
            envelope = json.loads(
                line,
                object_pairs_hook=pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    TraceAdapterError("TRACE_NONFINITE_JSON")
                ),
            )
        except (ValueError, RecursionError, UnicodeError):
            raise TraceAdapterError("TRACE_STREAM_JSON_INVALID") from None
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"result"}
            or not isinstance(envelope["result"], dict)
        ):
            raise TraceAdapterError("TRACE_STREAM_ENVELOPE_INVALID")
        resources = envelope["result"].get("resourceSpans", [])
        if envelope["result"] and "resourceSpans" not in envelope["result"]:
            raise TraceAdapterError("TRACE_RESOURCE_SPANS_MISSING")
        if not isinstance(resources, list):
            raise TraceAdapterError("TRACE_RESOURCE_SPANS_INVALID")
        for group in resources:
            if not isinstance(group, dict) or not isinstance(
                group.get("resource", {}), dict
            ):
                raise TraceAdapterError("TRACE_RESOURCE_INVALID")
            attrs = _attributes(
                group.get("resource", {}).get("attributes", []), {"service.name"}
            )
            service = attrs.get("service.name")
            if (
                not isinstance(service, str)
                or not service.strip()
                or len(service) > 512
            ):
                raise TraceAdapterError("TRACE_SERVICE_IDENTITY_MISSING")
            scopes = group.get("scopeSpans", [])
            if not isinstance(scopes, list):
                raise TraceAdapterError("TRACE_SCOPES_INVALID")
            for scope in scopes:
                if not isinstance(scope, dict) or not isinstance(
                    scope.get("spans", []), list
                ):
                    raise TraceAdapterError("TRACE_SCOPE_INVALID")
                for span in scope.get("spans", []):
                    if not isinstance(span, dict):
                        raise TraceAdapterError("TRACE_SPAN_INVALID")
                    trace_id = _identifier(span.get("traceId"), 32)
                    span_id = _identifier(span.get("spanId"), 16)
                    parent = _identifier(span.get("parentSpanId"), 16, parent=True)
                    start, end = (
                        _uint(span.get("startTimeUnixNano")),
                        _uint(span.get("endTimeUnixNano")),
                    )
                    if end < start:
                        raise TraceAdapterError("TRACE_NEGATIVE_DURATION")
                    kind = span.get("kind", 0)
                    if isinstance(kind, str) and kind.startswith("SPAN_KIND_"):
                        kind = next(
                            (
                                k
                                for k, v in KIND.items()
                                if v == kind.removeprefix("SPAN_KIND_")
                            ),
                            None,
                        )
                    if (
                        not isinstance(kind, int)
                        or isinstance(kind, bool)
                        or kind not in KIND
                    ):
                        raise TraceAdapterError("TRACE_KIND_INVALID")
                    status = span.get("status", {})
                    if not isinstance(status, dict):
                        raise TraceAdapterError("TRACE_STATUS_INVALID")
                    code = status.get("code", 0)
                    if (
                        not isinstance(code, (int, str))
                        or code
                        not in {
                            0,
                            1,
                            2,
                            "STATUS_CODE_UNSET",
                            "STATUS_CODE_OK",
                            "STATUS_CODE_ERROR",
                        }
                        or isinstance(code, bool)
                    ):
                        raise TraceAdapterError("TRACE_STATUS_CODE_INVALID")
                    attrs = _attributes(
                        span.get("attributes", []),
                        {"error", "http.status_code", "http.response.status_code"},
                    )
                    error = code in {2, "STATUS_CODE_ERROR"}
                    if "error" in attrs:
                        if not isinstance(attrs["error"], bool):
                            raise TraceAdapterError("TRACE_ERROR_TYPE_INVALID")
                        error = error or attrs["error"]
                    http = attrs.get(
                        "http.response.status_code", attrs.get("http.status_code")
                    )
                    if http is not None:
                        if (
                            isinstance(http, bool)
                            or not str(http).isdigit()
                            or not 100 <= int(http) <= 599
                        ):
                            raise TraceAdapterError("TRACE_HTTP_STATUS_INVALID")
                        error = error or int(http) >= 500
                    converted = {
                        "traceID": trace_id,
                        "spanID": span_id,
                        "processID": service,
                        "startTime": start // 1000,
                        "duration": (end - start) // 1000,
                        "references": [
                            {
                                "refType": "CHILD_OF",
                                "traceID": trace_id,
                                "spanID": parent,
                            }
                        ]
                        if parent
                        else [],
                        "tags": [
                            {"key": "span.kind", "value": KIND[kind]},
                            {"key": "error", "value": error},
                        ],
                    }
                    trace = traces.setdefault(
                        trace_id, {"traceID": trace_id, "spans": {}, "processes": {}}
                    )
                    old = trace["spans"].get(span_id)
                    if old is not None and old != converted:
                        raise TraceAdapterError("TRACE_CONFLICTING_SPAN")
                    if old is None:
                        span_count += 1
                        if span_count > MAX_CANONICAL_SPANS:
                            raise TraceAdapterError("TRACE_CANONICAL_SPAN_BUDGET")
                        if len(trace["spans"]) >= MAX_SPANS_PER_TRACE:
                            raise TraceAdapterError("TRACE_SINGLE_TRACE_SPAN_BUDGET")
                    trace["spans"][span_id] = converted
                    trace["processes"][service] = {"serviceName": service}
    if not envelopes:
        raise TraceAdapterError("TRACE_STREAM_EMPTY")
    return [
        trace | {"spans": list(trace["spans"].values())}
        for _, trace in sorted(traces.items())
    ]


def validate_canonical_spans(spans):
    """Reject unsafe graph/input shape before invoking unchanged model code.

    Parent cycles otherwise make descendant traversal non-terminating. Missing
    parents remain permitted (partial traces); no synthetic edges are created.
    """
    if not isinstance(spans, list) or len(spans) > MAX_CANONICAL_SPANS:
        raise TraceAdapterError("TRACE_CANONICAL_SPAN_BUDGET")
    parents = {}
    for span in spans:
        if not isinstance(span, dict):
            raise TraceAdapterError("TRACE_CANONICAL_SPAN_INVALID")
        for key in ("trace_id", "span_id", "service"):
            if (
                not isinstance(span.get(key), str)
                or not span[key]
                or len(span[key]) > 512
            ):
                raise TraceAdapterError("TRACE_CANONICAL_ID_INVALID")
        parent = span.get("parent_span_id", "")
        if not isinstance(parent, str) or len(parent) > 512:
            raise TraceAdapterError("TRACE_CANONICAL_PARENT_INVALID")
        for key in ("start_time_us", "duration_us"):
            value = span.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise TraceAdapterError("TRACE_CANONICAL_TIME_INVALID")
        graph = parents.setdefault(span["trace_id"], {})
        if span["span_id"] in graph:
            raise TraceAdapterError("TRACE_DUPLICATE_CANONICAL_SPAN")
        graph[span["span_id"]] = parent
        if len(graph) > MAX_SPANS_PER_TRACE:
            raise TraceAdapterError("TRACE_SINGLE_TRACE_SPAN_BUDGET")
    for graph in parents.values():
        visited = set()
        for identifier in graph:
            if identifier in visited:
                continue
            trail = set()
            cursor = identifier
            while cursor in graph and cursor not in visited:
                if cursor in trail:
                    raise TraceAdapterError("TRACE_PARENT_CYCLE")
                trail.add(cursor)
                cursor = graph[cursor]
            visited.update(trail)
    return spans
