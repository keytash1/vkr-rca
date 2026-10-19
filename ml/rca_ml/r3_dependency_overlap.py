"""Research-only role-free temporal overlap. Never claims blocking or CPU time."""
from collections import defaultdict
import math

import numpy as np

OVERLAP_FEATURES = (
    "dep_overlap_median", "dep_overlap_median_shift", "dep_overlap_p90_shift",
    "dep_residual_median_log_ratio", "dep_residual_p90_log_ratio",
    "dep_boundary_support", "dep_entry_observed", "dep_missing_parent_ratio",
    "dep_healthy_observed",
)
_FIELDS = {"trace_id", "span_id", "parent_span_id", "service", "peer_service",
           "start_time_us", "duration_us", "span_kind", "error", "observed_edge"}


def _union(intervals):
    total, right = 0.0, -math.inf
    for left, end in sorted(intervals):
        if end > max(left, right):
            total += end - max(left, right)
        right = max(right, end)
    return total


def summarize_overlap(spans, services, start_us, end_us):
    """Clip first cross-service frontier intervals to local entry operations."""
    if not all(math.isfinite(float(v)) for v in (start_us, end_us)) or end_us <= start_us:
        raise ValueError("invalid overlap interval")
    if len(set(services)) != len(services):
        raise ValueError("duplicate candidate")
    traces = defaultdict(dict)
    for span in spans:
        if set(span) - _FIELDS:
            raise ValueError("noncanonical field at overlap boundary")
        for field in ("trace_id", "span_id", "service"):
            if not isinstance(span.get(field), str) or not span[field]:
                raise ValueError("missing span identity")
        if not isinstance(span.get("parent_span_id", ""), str):
            raise ValueError("invalid parent")
        for field in ("start_time_us", "duration_us"):
            value = span[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("nonfinite or invalid span time")
        if span["duration_us"] < 0:
            raise ValueError("negative duration")
        group = traces[span["trace_id"]]
        if span["span_id"] in group:
            raise ValueError("duplicate span identity")
        group[span["span_id"]] = span
    values = {s: {"ratios": [], "residuals": [], "boundaries": 0, "missing_parent": 0,
                  "clipped_boundaries": 0} for s in services}
    for group in traces.values():
        children = defaultdict(list)
        for span in group.values():
            children[span.get("parent_span_id", "")].append(span)
        # Validate every connected component, including cycles with no entry.
        done = set()
        for identifier in group:
            chain, node = set(), identifier
            while node in group and node not in done:
                if node in chain:
                    raise ValueError("parent cycle")
                chain.add(node)
                node = group[node].get("parent_span_id", "")
            done.update(chain)
        for entry in group.values():
            service = entry["service"]
            if service not in values or not start_us <= entry["start_time_us"] <= end_us:
                continue
            parent_id = entry.get("parent_span_id", "")
            parent = group.get(parent_id)
            if parent and parent["service"] == service:
                continue
            left = float(entry["start_time_us"])
            duration = float(entry["duration_us"])
            right = left + duration
            pending = list(children[entry["span_id"]])
            intervals, boundary_count, clipped_count = [], 0, 0
            while pending:
                child = pending.pop()
                if child["service"] == service:
                    pending.extend(children[child["span_id"]])
                    continue
                boundary_count += 1
                a, b = float(child["start_time_us"]), float(child["start_time_us"] + child["duration_us"])
                clipped_count += int(a < left or b > right)
                a, b = max(a, left), min(b, right)
                if b > a:
                    intervals.append((a, b))
            overlap = min(duration, _union(intervals))
            row = values[service]
            row["ratios"].append(overlap / max(duration, 1.0))
            row["residuals"].append(max(0.0, duration - overlap))
            row["boundaries"] += int(boundary_count > 0)
            row["missing_parent"] += int(bool(parent_id) and parent is None)
            row["clipped_boundaries"] += clipped_count
    result = {}
    for service, row in values.items():
        count = len(row["ratios"])
        result[service] = dict(row, entries=count,
            overlap_median=float(np.median(row["ratios"])) if count else 0.0,
            overlap_p90=float(np.quantile(row["ratios"], .9)) if count else 0.0,
            overlap_iqr=float(np.subtract(*np.quantile(row["ratios"], [.75, .25]))) if count else 0.0,
            residual_median=float(np.median(row["residuals"])) if count else 0.0,
            residual_p90=float(np.quantile(row["residuals"], .9)) if count else 0.0)
    return result


def overlap_features(summary, healthy):
    output = {}
    for service, current in summary.items():
        normal = healthy.get(service, {})
        observed = bool(current["entries"])
        comparable = observed and bool(normal.get("entries"))
        scale = max(.01, normal.get("overlap_iqr", 0.0))
        def deviation(key):
            return (current[key] - normal[key]) / scale if comparable else 0.0
        def ratio(key):
            return math.log1p(current[key]) - math.log1p(normal[key]) if comparable else 0.0
        vals = (current["overlap_median"], deviation("overlap_median"), deviation("overlap_p90"),
                ratio("residual_median"), ratio("residual_p90"),
                current["boundaries"] / max(1, current["entries"]), float(observed),
                current["missing_parent"] / max(1, current["entries"]), float(bool(normal.get("entries"))))
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("nonfinite overlap feature")
        output[service] = dict(zip(OVERLAP_FEATURES, vals, strict=True))
    return output
