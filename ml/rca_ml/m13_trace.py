"""Canonical, identity-safe trace ingestion and service-level summaries for M13."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence

import numpy as np

FORBIDDEN_TRACE_KEYS = frozenset({
    "root", "root_service", "fault", "fault_type", "system", "dataset", "label",
})


def assert_trace_truth_free(records: Iterable[dict]) -> None:
    for record in records:
        leaked = FORBIDDEN_TRACE_KEYS & set(record)
        if leaked:
            raise ValueError(f"truth or semantic identity at trace boundary: {sorted(leaked)}")


def canonicalize_jaeger(payload: dict) -> list[dict]:
    """Convert Jaeger API traces to the frozen canonical span schema."""
    output = []
    for trace in payload.get("data", []):
        processes = trace.get("processes", {})
        raw_spans = trace.get("spans", [])
        service_by_span = {
            str(span["spanID"]): str(processes.get(span.get("processID"), {}).get("serviceName", "unknown"))
            for span in raw_spans
        }
        for span in raw_spans:
            tags = {str(tag.get("key")): tag.get("value") for tag in span.get("tags", [])}
            parent = next(
                (str(ref.get("spanID")) for ref in span.get("references", []) if ref.get("refType") == "CHILD_OF"),
                "",
            )
            service = service_by_span[str(span["spanID"])]
            parent_service = service_by_span.get(parent, "")
            kind = str(tags.get("span.kind", "UNKNOWN")).upper()
            status = tags.get("http.status_code", tags.get("status.code", 0))
            try:
                status_error = int(status) >= 500
            except (TypeError, ValueError):
                status_error = str(status).upper() in {"ERROR", "STATUS_CODE_ERROR"}
            error = bool(tags.get("error", False)) or status_error
            output.append({
                "trace_id": str(span["traceID"]),
                "span_id": str(span["spanID"]),
                "parent_span_id": parent,
                "service": service,
                "peer_service": parent_service if parent_service and parent_service != service else "",
                "start_time_us": int(span["startTime"]),
                "duration_us": max(0, int(span.get("duration", 0))),
                "span_kind": kind if kind in {"SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"} else "UNKNOWN",
                "error": error,
                "observed_edge": (
                    {"source": parent_service, "target": service}
                    if parent_service and parent_service != service else None
                ),
            })
    assert_trace_truth_free(output)
    output.sort(key=lambda item: (item["trace_id"], item["start_time_us"], item["span_id"]))
    return output


def union_duration(intervals: Sequence[tuple[int, int]]) -> int:
    """Return the exact union length of possibly overlapping half-open intervals."""
    ordered = sorted((int(start), int(end)) for start, end in intervals if end > start)
    if not ordered:
        return 0
    total = 0
    left, right = ordered[0]
    for start, end in ordered[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def exclusive_duration_us(span: dict, trace_spans: Sequence[dict]) -> tuple[int, int]:
    """Observed server duration minus union of same-service client-descendant waits."""
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for item in trace_spans:
        by_parent[str(item.get("parent_span_id", ""))].append(item)
    descendants, pending = [], list(by_parent.get(str(span["span_id"]), []))
    while pending:
        item = pending.pop()
        descendants.append(item)
        pending.extend(by_parent.get(str(item["span_id"]), []))
    start = int(span["start_time_us"])
    end = start + int(span["duration_us"])
    waits = []
    for item in descendants:
        if item["service"] != span["service"] or item["span_kind"] != "CLIENT":
            continue
        child_start = max(start, int(item["start_time_us"]))
        child_end = min(end, int(item["start_time_us"]) + int(item["duration_us"]))
        if child_end > child_start:
            waits.append((child_start, child_end))
    wait = min(int(span["duration_us"]), union_duration(waits))
    return max(0, int(span["duration_us"]) - wait), wait


def summarize_window(
    spans: Sequence[dict], services: Sequence[str], start_us: int, end_us: int
) -> tuple[dict[str, dict], dict[tuple[str, str], int]]:
    """Summarize canonical spans without operation or service identity features."""
    assert_trace_truth_free(spans)
    duration_seconds = max((end_us - start_us) / 1_000_000, 1e-6)
    selected = [item for item in spans if start_us <= int(item["start_time_us"]) <= end_us]
    by_trace: dict[str, list[dict]] = defaultdict(list)
    by_service: dict[str, list[dict]] = defaultdict(list)
    edges: dict[tuple[str, str], int] = defaultdict(int)
    for item in selected:
        by_trace[item["trace_id"]].append(item)
        by_service[item["service"]].append(item)
        edge = item.get("observed_edge")
        if edge and edge["source"] != edge["target"]:
            edges[(edge["source"], edge["target"])] += 1

    result = {}
    for service in sorted(set(map(str, services))):
        local = by_service.get(service, [])
        server = [item for item in local if item["span_kind"] in {"SERVER", "UNKNOWN"}]
        timed = server or local
        durations = [float(item["duration_us"]) for item in timed]
        exclusive, waits = [], []
        for item in server:
            value, wait = exclusive_duration_us(item, by_trace[item["trace_id"]])
            exclusive.append(float(value))
            waits.append(wait / max(float(item["duration_us"]), 1.0))
        last_seen = max((int(item["start_time_us"]) for item in local), default=start_us)
        result[service] = {
            "span_rate": len(local) / duration_seconds,
            "request_rate": len(server) / duration_seconds,
            "error_rate": float(np.mean([bool(item["error"]) for item in timed])) if timed else 0.0,
            "latency_median_us": _quantile(durations, .5),
            "latency_p90_us": _quantile(durations, .9),
            "latency_p99_us": _quantile(durations, .99),
            "exclusive_median_us": _quantile(exclusive, .5),
            "downstream_wait_ratio": _quantile(waits, .5),
            "last_seen_delta_s": max(0.0, (end_us - last_seen) / 1_000_000),
            "trace_coverage": float(bool(local)),
            "span_count": len(local),
            "request_count": len(server),
        }
    return result, dict(edges)


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    value = float(np.quantile(np.asarray(values, dtype=float), fraction))
    if not math.isfinite(value):
        raise ValueError("non-finite trace summary")
    return value
