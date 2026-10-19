"""Research-only time-shape features. Not imported by the product runtime."""
from collections import defaultdict
import math
import numpy as np

TEMPORAL_FEATURES = (
    "time_metric_early_shift", "time_metric_late_shift", "time_metric_trend",
    "time_metric_first_fraction", "time_metric_deviation_observed",
    "time_trace_early_error_rate", "time_trace_late_error_rate", "time_trace_error_trend",
    "time_trace_first_error_fraction", "time_trace_error_observed",
)


def temporal_features(incident, baseline, services):
    allowed = {"start_unix", "end_unix", "requests_per_second", "metrics", "traces", "traces_collected"}
    if set(incident) - allowed:
        raise ValueError("non-canonical fields at temporal feature boundary")
    start, end, rps = (float(incident[k]) for k in ("start_unix", "end_unix", "requests_per_second"))
    if not all(map(math.isfinite, (start, end, rps))) or end <= start:
        raise ValueError("invalid temporal interval")
    duration = end - start
    metric = defaultdict(lambda: defaultdict(list))
    spans = defaultdict(list)
    for point in incident["metrics"]:
        timestamp, value = float(point["timestamp"]), float(point["value"])
        if not math.isfinite(timestamp + value):
            raise ValueError("nonfinite metric")
        if start <= timestamp <= end and point["service"] in services:
            normal = baseline["metric"].get(point["service"], {}).get(point["family"])
            if not normal:
                continue
            scale = float(normal["residual_iqr"])
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError("invalid baseline scale")
            expected = normal["intercept"] + normal["slope"] * rps + normal.get("residual_median", 0)
            shift = abs((value - expected) / scale)
            metric[point["service"]][point["family"]].append(((timestamp - start) / duration, shift))
    for span in incident["traces"]:
        stamp = float(span["start_time_us"]) / 1e6
        if not math.isfinite(stamp):
            raise ValueError("nonfinite span time")
        if start <= stamp <= end and span["service"] in services:
            spans[span["service"]].append(((stamp - start) / duration, bool(span["error"])))
    result = {}
    for service in sorted(services):
        early, late, onset = [], [], []
        for points in metric[service].values():
            first = [v for t, v in points if t <= 1 / 3]
            last = [v for t, v in points if t >= 2 / 3]
            if first:
                early.append(float(np.quantile(first, .9)))
            if last:
                late.append(float(np.quantile(last, .9)))
            onset.extend(t for t, v in points if v >= 3)
        a, b = max(early, default=0.0), max(late, default=0.0)
        first_spans = [error for t, error in spans[service] if t <= 1 / 3]
        last_spans = [error for t, error in spans[service] if t >= 2 / 3]
        x, y = sum(first_spans) / max(1, len(first_spans)), sum(last_spans) / max(1, len(last_spans))
        errors = [t for t, error in spans[service] if error]
        values = (a, b, b - a, min(onset, default=1.0), float(bool(onset)),
                  x, y, y - x, min(errors, default=1.0), float(bool(errors)))
        if not all(map(math.isfinite, values)):
            raise ValueError("nonfinite temporal feature")
        result[service] = dict(zip(TEMPORAL_FEATURES, values, strict=True))
    return result


def temporal_heuristic(features, metric_shifts):
    def key(service):
        f = features[service]
        observed = bool(f["time_metric_deviation_observed"] or f["time_trace_error_observed"])
        first = min(f["time_metric_first_fraction"], f["time_trace_first_error_fraction"])
        return (not observed, first, -metric_shifts[service], service)
    ordered = sorted(features, key=key)
    # Position scores express only this lexicographic rule, never probabilities.
    return [{"service": s, "rank": i + 1, "score": float(len(ordered) - i)} for i, s in enumerate(ordered)]
