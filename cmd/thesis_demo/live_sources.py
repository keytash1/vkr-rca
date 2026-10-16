"""Profile-based, read-only collection for a known incident interval.

Profiles are operator-installed files, never supplied in an HTTP request. The
collector returns the same truth-free canonical window used by replay tests.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rca_ml.m12_adapter import CANONICAL_UNITS
from rca_ml.m13_trace import canonicalize_jaeger


FAMILIES = tuple(CANONICAL_UNITS)
MAX_WINDOW_SECONDS = 3600
TRACE_CHUNK_SECONDS = 300
TRACE_LIMIT = 1000
MAX_TRACE_QUERIES = 128
MAX_COLLECTION_SECONDS = 120


class TelemetrySourceError(OSError):
    """The configured source failed or violated the expected response contract."""


def _endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid telemetry endpoint in profile")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("telemetry endpoint must be a base URL")
    return value.rstrip("/")


def _get_json(base: str, path: str, params: dict, token_env: str | None,
              timeout: float = 30) -> dict:
    headers = {"Accept": "application/json"}
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise ValueError(f"telemetry credential is missing: {token_env}")
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base}{path}?{urlencode(params)}"
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            if response.status != 200:
                raise OSError(f"telemetry source returned HTTP {response.status}")
            payload = response.read(32 * 1024 * 1024 + 1)
    except HTTPError as error:
        code = error.code
        error.close()
        raise OSError(f"telemetry source returned HTTP {code}") from error
    except URLError as error:
        raise TelemetrySourceError(f"telemetry source is unreachable at {base}") from error
    if len(payload) > 32 * 1024 * 1024:
        raise TelemetrySourceError("telemetry response exceeds 32 MiB")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise TelemetrySourceError("telemetry response is not JSON") from error
    if not isinstance(value, dict):
        raise TelemetrySourceError("telemetry response must be an object")
    return value


@dataclass(frozen=True)
class LiveProfile:
    id: str
    title: str
    services: tuple[str, ...]
    aliases: dict[str, str]
    ignored_service_labels: frozenset[str]
    metrics_url: str
    metric_queries: dict[str, str]
    metric_service_label: str
    metric_token_env: str | None
    traces_url: str
    trace_query_services: tuple[str, ...]
    trace_token_env: str | None
    fixed_rps: float | None
    rps_query: str | None
    artifact_dir: Path
    version: str

    @classmethod
    def load(cls, path: Path, root: Path, *, require_artifacts: bool = True) -> "LiveProfile":
        raw = json.loads(path.read_text())
        profile_id = raw["id"]
        if not isinstance(profile_id, str) or not profile_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in profile_id):
            raise ValueError("invalid profile id")
        services = tuple(raw["candidate_services"])
        if not services or services != tuple(sorted(set(services))) or any(not isinstance(s, str) or not s for s in services):
            raise ValueError(f"profile {profile_id}: candidate services must be sorted and unique")
        metric = raw["metrics"]
        queries = metric["queries"]
        if set(queries) != set(FAMILIES) or any(not isinstance(queries[f], str) or not queries[f] for f in FAMILIES):
            raise ValueError(f"profile {profile_id}: four metric-family queries are required")
        trace = raw["traces"]
        trace_services = tuple(trace["query_services"])
        if not trace_services or any(not isinstance(s, str) or not s for s in trace_services):
            raise ValueError(f"profile {profile_id}: at least one trace entry service is required")
        workload = raw["workload"]
        fixed = workload.get("fixed_requests_per_second")
        query = workload.get("prometheus_query")
        if (fixed is None) == (query is None):
            raise ValueError(f"profile {profile_id}: select exactly one workload source")
        if fixed is not None and (isinstance(fixed, bool) or not math.isfinite(float(fixed)) or float(fixed) <= 0):
            raise ValueError(f"profile {profile_id}: invalid fixed workload")
        if query is not None and (not isinstance(query, str) or not query):
            raise ValueError(f"profile {profile_id}: invalid workload query")
        aliases = dict(raw.get("service_aliases", {}))
        if any(not isinstance(k, str) or v not in services for k, v in aliases.items()):
            raise ValueError(f"profile {profile_id}: invalid service alias")
        artifact_dir = (root / raw["artifact_dir"]).resolve()
        if not artifact_dir.is_relative_to(root.resolve()):
            raise ValueError(f"profile {profile_id}: invalid artifact directory")
        if require_artifacts:
            for name in ("healthy-baseline.json", "legacy-metric-baseline.json"):
                if not (artifact_dir / name).is_file():
                    raise ValueError(f"profile {profile_id}: missing {name}")
            baseline = json.loads((artifact_dir / "healthy-baseline.json").read_text())
            if set(baseline["metric"]) != set(services):
                raise ValueError(f"profile {profile_id}: baseline candidate universe differs")
            if set(baseline["trace"]) != set(services):
                raise ValueError(f"profile {profile_id}: trace baseline candidate universe differs")
        return cls(
            id=profile_id,
            title=str(raw["title"]),
            services=services,
            aliases=aliases,
            ignored_service_labels=frozenset(raw.get("ignored_service_labels", [])),
            metrics_url=_endpoint(metric["url"]),
            metric_queries=queries,
            metric_service_label=str(metric.get("service_label", "service")),
            metric_token_env=metric.get("token_env"),
            traces_url=_endpoint(trace["url"]),
            trace_query_services=trace_services,
            trace_token_env=trace.get("token_env"),
            fixed_rps=float(fixed) if fixed is not None else None,
            rps_query=query,
            artifact_dir=artifact_dir,
            version=str(raw["version"]),
        )

    def service(self, name: str) -> str | None:
        if name in self.ignored_service_labels:
            return None
        canonical = self.aliases.get(name, name)
        if canonical not in self.services:
            raise ValueError(f"unmapped telemetry service: {name}")
        return canonical


def _remaining(deadline: float | None) -> float:
    if deadline is None:
        return 30
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TelemetrySourceError("telemetry collection exceeded its time budget")
    return min(30, remaining)


def _prometheus(profile: LiveProfile, query: str, start: float, end: float,
                deadline: float | None = None) -> list[dict]:
    data = _get_json(
        profile.metrics_url,
        "/api/v1/query_range",
        {"query": query, "start": start, "end": end, "step": "1s"},
        profile.metric_token_env, _remaining(deadline),
    )
    if data.get("status") != "success" or data.get("data", {}).get("resultType") != "matrix":
        raise TelemetrySourceError("invalid Prometheus query_range response")
    result = data["data"].get("result")
    if not isinstance(result, list):
        raise TelemetrySourceError("invalid Prometheus series")
    return result


def _jaeger_interval(profile: LiveProfile, service: str, left: float, right: float,
                     budget: list[int], deadline: float | None = None) -> list[dict]:
    """Split a saturated search instead of silently dropping traces at limit."""
    budget[0] -= 1
    if budget[0] < 0:
        raise TelemetrySourceError("trace search exceeded its request budget")
    payload = _get_json(
        profile.traces_url, "/api/traces",
        {"service": service, "start": int(left * 1_000_000),
         "end": int(right * 1_000_000), "limit": TRACE_LIMIT},
        profile.trace_token_env, _remaining(deadline),
    )
    traces = payload.get("data")
    if not isinstance(traces, list):
        raise TelemetrySourceError("invalid Jaeger trace response")
    if len(traces) < TRACE_LIMIT:
        return traces
    if right - left <= 1:
        raise TelemetrySourceError("trace search remains saturated at one-second resolution")
    middle = (left + right) / 2
    return (_jaeger_interval(profile, service, left, middle, budget, deadline)
            + _jaeger_interval(profile, service, middle, right, budget, deadline))


def collect(profile: LiveProfile, start: float, end: float) -> tuple[dict, dict]:
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
        or not math.isfinite(start) or not math.isfinite(end)
        or start <= 0 or end <= start or end - start > MAX_WINDOW_SECONDS
    ):
        raise ValueError("invalid incident interval")
    metrics: list[dict] = []
    deadline = time.monotonic() + MAX_COLLECTION_SECONDS
    coverage = {service: set() for service in profile.services}
    seen_metric_points = set()
    for family in FAMILIES:
        for series in _prometheus(profile, profile.metric_queries[family], start, end, deadline):
            labels = series.get("metric", {})
            name = labels.get(profile.metric_service_label)
            if not isinstance(name, str):
                raise TelemetrySourceError("metric series has no configured service label")
            service = profile.service(name)
            if service is None:
                continue
            for timestamp, value in series.get("values", []):
                timestamp = float(timestamp)
                value = float(value)
                if not math.isfinite(timestamp) or not math.isfinite(value):
                    continue
                if start <= timestamp <= end:
                    point = (timestamp, service, family)
                    if point in seen_metric_points:
                        raise TelemetrySourceError(
                            f"duplicate metric series for {service}/{family}; aggregate by service in the profile query"
                        )
                    seen_metric_points.add(point)
                    metrics.append({
                        "timestamp": int(timestamp), "service": service, "family": family,
                        "value": value, "unit": CANONICAL_UNITS[family],
                    })
                    coverage[service].add(family)
    if not metrics:
        raise TelemetrySourceError("no metric observations for the configured candidates")
    metrics.sort(key=lambda item: (item["timestamp"], item["service"], item["family"]))
    traces_by_id = {}
    trace_error = None
    try:
        budget = [MAX_TRACE_QUERIES]
        for entry_service in profile.trace_query_services:
            left = start
            while left < end:
                right = min(end, left + TRACE_CHUNK_SECONDS)
                for trace in _jaeger_interval(profile, entry_service, left, right, budget, deadline):
                    traces_by_id[str(trace["traceID"])] = trace
                left = right
        spans = canonicalize_jaeger({"data": list(traces_by_id.values())})
        traces = []
        for span in spans:
            # A trace can legitimately contain a supporting service outside
            # the candidate universe. Keep it as context, as in M14 replay.
            service = profile.aliases.get(span["service"], span["service"])
            parent = span["peer_service"]
            if parent:
                span["peer_service"] = profile.aliases.get(parent, parent)
            edge = span.get("observed_edge")
            if edge:
                span["observed_edge"] = {
                    "source": profile.aliases.get(edge["source"], edge["source"]),
                    "target": profile.aliases.get(edge["target"], edge["target"]),
                }
            span["service"] = service
            traces.append(span)
    except (OSError, TimeoutError, ValueError, KeyError, TypeError) as error:
        traces, trace_error = [], str(error)
    incident_id = "live-" + hashlib.sha256(
        f"{profile.id}:{start:.6f}:{end:.6f}".encode()
    ).hexdigest()[:16]
    rps = profile.fixed_rps
    if rps is None:
        values = []
        for series in _prometheus(profile, profile.rps_query or "", start, end, deadline):
            values.extend(float(value) for _, value in series.get("values", []) if math.isfinite(float(value)))
        if not values:
            raise TelemetrySourceError("workload intensity is unavailable")
        rps = sum(values) / len(values)
    if not math.isfinite(rps) or rps <= 0:
        raise ValueError("invalid workload intensity")
    window = {
        "incident_id": incident_id,
        "start_unix": start,
        "end_unix": end,
        "candidate_services": list(profile.services),
        "requests_per_second": rps,
        "metrics": metrics,
        "traces": traces,
        "traces_collected": trace_error is None,
    }
    status = {
        "metrics": "available",
        "traces": "available" if trace_error is None else "unavailable",
        "trace_error": trace_error,
        "metric_families_by_service": {s: sorted(families) for s, families in coverage.items()},
        "metric_sample_count": len(metrics),
        "span_count": len(traces),
    }
    return window, status
