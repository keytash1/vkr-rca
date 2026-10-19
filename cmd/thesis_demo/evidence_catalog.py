"""Bounded, truth-free observations; independent of the ranking algorithm.

No network I/O, model calls, source credentials or arbitrary telemetry fields.
The registry is an expiring projection, NOT durable investigation storage.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
import hashlib
import json
import math
import re
from statistics import median
import threading
import time
from urllib.parse import urlencode, urlsplit

from rca_ml.m12_adapter import CANONICAL_UNITS
from assistant_context import assistant_context as assistant_context  # Explicit re-export.
from trace_evidence import summarize_timings
from baseline_applicability import assess as assess_baseline

MAX_SERIES_POINTS = 64
MAX_TRACE_EXAMPLES = 3
TRACE_ID = re.compile(r"[0-9a-fA-F]{16,32}\Z")


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _source_link(base, path, params):
    """Only installed source URLs, never credentials or caller-supplied URLs."""
    parts = urlsplit(base)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("invalid installed source link")
    return base.rstrip("/") + path + "?" + urlencode(params)


def _series(points):
    """Time-ordered min/max/mean bins; never present bin means as raw samples."""
    if not points:
        return []
    ordered = sorted(points)
    size = max(1, math.ceil(len(ordered) / MAX_SERIES_POINTS))
    return [{"start_unix": group[0][0], "end_unix": group[-1][0],
             "min": min(v for _, v in group), "max": max(v for _, v in group),
             "mean": sum(v for _, v in group) / len(group), "samples": len(group)}
            for offset in range(0, len(ordered), size)
            for group in [ordered[offset:offset + size]]]


def _quantile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def build_catalog(window, result, baseline, *, profile=None, source_status=None,
                  baseline_provenance=None):
    """Build only from explicit canonical fields; never from ML feature vectors."""
    start, end = result["start_unix"], result["end_unix"]
    services = sorted(window["candidate_services"])
    timings = summarize_timings(window["traces"], services, start*1e6, end*1e6)
    metrics, traces = defaultdict(list), defaultdict(list)
    for point in window["metrics"]:
        service, family = point["service"], point["family"]
        stamp, value = float(point["timestamp"]), float(point["value"])
        if service in services and family in CANONICAL_UNITS and start <= stamp <= end:
            if point["unit"] != CANONICAL_UNITS[family] or not math.isfinite(value):
                raise ValueError("noncanonical metric observation")
            metrics[(service, family)].append((stamp, value))
    edges = defaultdict(int)
    external_edges = defaultdict(int)
    for span in window["traces"]:
        if start * 1e6 <= span["start_time_us"] <= end * 1e6:
            if span["service"] in services:
                traces[span["service"]].append(span)
            edge = span.get("observed_edge")
            if edge and edge["source"] in services and edge["target"] in services:
                if edge["source"] != edge["target"]:
                    edges[(edge["source"], edge["target"])] += 1
            elif edge:
                for candidate in (edge["source"], edge["target"]):
                    if candidate in services:
                        external_edges[candidate] += 1
    status = source_status if source_status is not None else {
        "traces": ("unavailable" if window.get("traces_collected") is False else
                   "available" if window.get("traces_collected") is True else "REPLAY_STATUS_UNKNOWN")}
    baseline_provenance = baseline_provenance or {}
    rps = float(window["requests_per_second"])
    observations, checks = [], []

    def add(service, kind, values, links=()):
        fact = {"service": service, "kind": kind, "start_unix": start,
                "end_unix": end, "values": values}
        fact["id"] = "obs-" + digest({"input": result["input_sha256"],
            "baseline": result["baseline_sha256"], "fact": fact})[:32]
        fact["source_links"] = list(links)
        observations.append(fact)
        return fact["id"]

    def check(service, code, evidence_id, text):
        checks.append({"service": service, "code": code, "evidence_ids": [evidence_id],
                       "text": text, "status": "PROPOSED_NOT_EXECUTED"})

    for service in services:
        for family, unit in sorted(CANONICAL_UNITS.items()):
            points = metrics[(service, family)]
            values = [v for _, v in points]
            normal = baseline.get("metric", {}).get(service, {}).get(family)
            comparison = None
            if values and normal and normal.get("samples", 0) > 0:
                expected = (float(normal["intercept"]) + float(normal["slope"]) * rps
                            + float(normal.get("residual_median", 0)))
                scale = float(normal["residual_iqr"])
                if scale <= 0 or not math.isfinite(expected + scale):
                    raise ValueError("invalid baseline comparison")
                comparison = {"expected_at_observed_load": expected, "residual_iqr": scale,
                    "absolute_residual_p90": _quantile([abs(v - expected) / scale for v in values], .9),
                    "method": "workload_linear_prediction_and_residual_iqr",
                    "healthy_start_unix": baseline_provenance.get("healthy_start_unix"),
                    "healthy_end_unix": baseline_provenance.get("healthy_end_unix"),
                    "load_comparability": "NOT_ESTABLISHED"}
            coverage = status.get("metric_point_coverage", {}).get(service, {}).get(family)
            links = []
            if profile:
                links = [{"kind": "prometheus_query_range", "url": _source_link(
                    profile.metrics_url, "/api/v1/query_range", {
                        "query": profile.metric_queries[family], "start": start,
                        "end": end, "step": profile.query_step_seconds})}]
            identifier = add(service, "metric", {"family": family, "unit": unit,
                "samples": len(values), "min": min(values) if values else None,
                "median": median(values) if values else None,
                "max": max(values) if values else None, "returned_point_coverage": coverage,
                "state": "OBSERVED" if values else "MISSING",
                "baseline_comparison": comparison, "series": _series(points)}, links)
            if not values or (coverage is not None and coverage < .8):
                check(service, "CHECK_METRIC_COVERAGE", identifier,
                      f"Проверить покрытие ряда {family}, метки и активность сервиса; пропуск не означает нормальное состояние.")
            if comparison and comparison["absolute_residual_p90"] >= 3:
                check(service, "CHECK_METRIC_DEVIATION", identifier,
                      f"Сопоставить изменение {family} с нагрузкой, единицами и здоровым периодом; отклонение не устанавливает причину.")
        local = traces[service]
        trace_state = ("UNAVAILABLE" if status.get("traces") == "unavailable"
                       else "OBSERVED" if local else "NOT_OBSERVED")
        # IDs are allowed; arbitrary tag/operation/url fields never leave this module.
        examples = []
        for span in sorted(local, key=lambda s: (not bool(s["error"]), -s["duration_us"], str(s["span_id"]))):
            trace_id, span_id = str(span["trace_id"]), str(span["span_id"])
            if not TRACE_ID.fullmatch(trace_id) or not TRACE_ID.fullmatch(span_id):
                continue
            examples.append({"trace_id": trace_id, "span_id": span_id,
                "start_time_us": span["start_time_us"], "duration_us": span["duration_us"],
                "error": bool(span["error"])})
            if len(examples) == MAX_TRACE_EXAMPLES:
                break
        links = []
        if profile:
            source_names = sorted({service} | {k for k, v in profile.aliases.items() if v == service})
            links = [{"kind": "jaeger_trace_search", "url": _source_link(
                profile.traces_url, "/api/traces", {"service": name,
                    "start": int(start * 1e6), "end": int(end * 1e6), "limit": 100})}
                for name in source_names]
        identifier = add(service, "traces", {"state": trace_state,
            "observed_spans": len(local), "observed_error_spans": sum(bool(s["error"]) for s in local),
            "sampling": "UNKNOWN", "retention": "UNKNOWN", "examples": examples,
            "timing": timings[service],
            "example_selection": "error_first_then_longest_duration_not_random"}, links)
        if trace_state != "OBSERVED":
            check(service, "CHECK_TRACE_AVAILABILITY", identifier,
                  "Проверить источник, инструментирование, sampling и активность: отсутствие спанов не доказывает отсутствие вызовов.")
        elif any(s["error"] for s in local):
            check(service, "INSPECT_ERROR_TRACES", identifier,
                  "Открыть примеры ошибочных трасс и сопоставить локальную операцию с зависимостями; выборка не определяет частоту ошибок всего трафика.")
        dependencies = [{"source": a, "target": b, "observed_edges": n}
                        for (a, b), n in sorted(edges.items()) if service in (a, b)]
        identifier = add(service, "dependencies", {"edges": dependencies, "state": trace_state,
            "external_edge_observations": external_edges[service],
            "meaning": "OBSERVED_CALLS_NOT_CAUSAL_PROOF"})
        if external_edges[service]:
            check(service, "CHECK_CANDIDATE_INVENTORY", identifier,
                  "В трассах наблюдаются связи за пределами списка кандидатов. Проверить полноту профиля и эти зависимости в источнике; их отсутствие в рейтинге не означает исправность.")
    return {"schema_version": "2.0", "catalog_version": "evidence-v2-source-timings",
        "analysis_id": result["result_id"], "profile_id": profile.id if profile else None,
        "profile_version": profile.version if profile else None,
        "input_sha256": result["input_sha256"], "baseline_sha256": result["baseline_sha256"],
        "model_version": result["model_version"], "feature_schema_sha256": result["feature_schema_sha256"],
        "start_unix": start, "end_unix": end, "services": services,
        "requests_per_second": rps,
        "source_quality": {"traces": status.get("traces", "REPLAY_STATUS_UNKNOWN"),
            "baseline_applicability": assess_baseline(baseline_provenance, start, end, rps,
                                                       status.get("workload_source")),
            "sampling": "UNKNOWN", "retention": "UNKNOWN",
            "source_annotation_count": len(status.get("annotations", [])),
            "collected_at_unix": status.get("collected_at_unix")},
        "observations": observations, "checks": checks,
        "limitations": ["DIAGNOSTIC_OBSERVATIONS_NOT_CAUSAL_PROOF",
                         "BASELINE_LOAD_COMPARABILITY_NOT_ESTABLISHED",
                         "SOURCE_LINKS_MAY_EXPIRE_OR_REQUIRE_SEPARATE_AUTH"]}


class EvidenceRegistry:
    """Bounded TTL store; caller receives copies, not mutable shared state."""
    def __init__(self, *, max_entries=16, max_bytes=32 * 1024 * 1024,
                 max_entry_bytes=4 * 1024 * 1024, ttl_seconds=1800, clock=time.monotonic):
        if min(max_entries, max_bytes, max_entry_bytes, ttl_seconds) <= 0:
            raise ValueError("registry limits must be positive")
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.max_entry_bytes, self.ttl_seconds = max_entry_bytes, ttl_seconds
        self.clock, self.lock = clock, threading.Lock()
        self.entries = OrderedDict()

    def _prune(self):
        now = self.clock()
        for key in list(self.entries):
            if self.entries[key][0] <= now:
                del self.entries[key]

    def put(self, catalog):
        payload = canonical_bytes(catalog)
        if len(payload) > min(self.max_entry_bytes, self.max_bytes):
            raise ValueError("evidence catalog exceeds registry budget")
        with self.lock:
            self._prune()
            self.entries[catalog["analysis_id"]] = (self.clock() + self.ttl_seconds, payload)
            self.entries.move_to_end(catalog["analysis_id"])
            while len(self.entries) > self.max_entries or sum(len(v[1]) for v in self.entries.values()) > self.max_bytes:
                self.entries.popitem(last=False)

    def get(self, analysis_id):
        with self.lock:
            self._prune()
            item = self.entries.get(analysis_id)
            return json.loads(item[1]) if item else None

    def delete(self,analysis_id):
        with self.lock:
            return self.entries.pop(analysis_id,None) is not None
