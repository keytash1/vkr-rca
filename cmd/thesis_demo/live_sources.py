"""Profile-based, read-only collection for a known incident interval.

Profiles are operator-installed files, never supplied in an HTTP request. The
collector returns the same truth-free canonical window used by replay tests.
"""

from __future__ import annotations

import hashlib
import contextvars
import functools
import json
import math
import os
import time
from http.client import IncompleteRead
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from rca_ml.m12_adapter import CANONICAL_UNITS
from rca_ml.m13_trace import canonicalize_jaeger
from api_errors import ApiError
from trace_adapters import TraceAccumulator, decode_v3_stream,v3_query,validate_canonical_spans,is_v3_no_matches
from profile_contract import baseline_binding, validate_semantic_map


FAMILIES = tuple(CANONICAL_UNITS)
MAX_WINDOW_SECONDS = 3600
TRACE_CHUNK_SECONDS = 300
TRACE_LIMIT = 1000
MAX_TRACE_QUERIES = 128
MAX_COLLECTION_SECONDS = 120
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_source_budget = contextvars.ContextVar("telemetry_source_byte_budget", default=None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A configured bearer token must never be forwarded to another origin.
        return None


def _bounded_collection(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        token = _source_budget.set([MAX_SOURCE_BYTES])
        try:
            return function(*args, **kwargs)
        finally:
            _source_budget.reset(token)
    return wrapped


class TelemetrySourceError(OSError):
    """The configured source failed or violated the expected response contract."""

    def __init__(self, message: str, code: str = "TELEMETRY_INVALID"):
        super().__init__(message)
        self.code = code


def _endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid telemetry endpoint in profile")
    if parsed.port is not None and parsed.port == 0:
        raise ValueError("invalid telemetry port in profile")
    if parsed.query or parsed.fragment:
        raise ValueError("telemetry base URL must not contain a query or fragment")
    return value.rstrip("/")


def _get_payload(base: str, path: str, params: dict, token_env: str | None,
              timeout: float = 30, *, v3_empty_search=False) -> bytes:
    headers = {"Accept": "application/json"}
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise TelemetrySourceError("telemetry credential is missing", "TELEMETRY_UNAVAILABLE")
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base}{path}?{urlencode(params)}"
    budget = _source_budget.get()
    limit = min(32 * 1024 * 1024, budget[0]) if budget is not None else 32 * 1024 * 1024
    if limit <= 0:
        raise TelemetrySourceError("telemetry collection exceeds 64 MiB")
    try:
        with build_opener(_NoRedirect()).open(Request(url, headers=headers), timeout=timeout) as response:
            if response.status != 200:
                raise OSError(f"telemetry source returned HTTP {response.status}")
            payload = response.read(limit + 1)
    except HTTPError as error:
        code = error.code
        if v3_empty_search and path == "/api/v3/traces" and code == 404:
            empty_body = error.read(min(4096,limit)+1)
            if len(empty_body) <= min(4096,limit) and is_v3_no_matches(empty_body):
                error.close()
                if budget is not None:
                    budget[0] -= len(empty_body)
                return b'{"result":{}}'
        error.close()
        raise OSError(f"telemetry source returned HTTP {code}") from error
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError("telemetry source timed out") from error
        raise TelemetrySourceError("telemetry source is unreachable", "TELEMETRY_UNAVAILABLE") from error
    except IncompleteRead:
        raise TelemetrySourceError("telemetry response stream was interrupted") from None
    if len(payload) > limit:
        raise TelemetrySourceError("telemetry response exceeds its byte budget")
    if budget is not None:
        budget[0] -= len(payload)
    return payload


def _get_json(base: str, path: str, params: dict, token_env: str | None,
              timeout: float = 30) -> dict:
    payload=_get_payload(base,path,params,token_env,timeout)
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError,UnicodeError,RecursionError) as error:
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
    query_step_seconds: int = 1
    baseline_min_coverage: float = 0.8
    trace_contract: str = "jaeger-http-json"
    trace_version: str = "unspecified"
    semantic_map: dict | None = None

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
        semantic_map = metric.get("semantic_map")
        if semantic_map is not None:
            validate_semantic_map(semantic_map)
        queries = metric["queries"]
        if set(queries) != set(FAMILIES) or any(not isinstance(queries[f], str) or not queries[f] for f in FAMILIES):
            raise ValueError(f"profile {profile_id}: four metric-family queries are required")
        trace = raw["traces"]
        trace_contract = trace.get("api", "jaeger-http-json")
        if trace_contract not in {"jaeger-http-json","jaeger-v3-json"}:
            raise ValueError(f"profile {profile_id}: unsupported trace API contract")
        step = metric.get("query_step_seconds", 1)
        if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 60:
            raise ValueError(f"profile {profile_id}: query step must be an integer from 1 to 60 seconds")
        minimum = metric.get("baseline_min_coverage", 0.8)
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 < minimum <= 1:
            raise ValueError(f"profile {profile_id}: invalid baseline coverage requirement")
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
        profile = cls(
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
            query_step_seconds=step,
            baseline_min_coverage=float(minimum),
            trace_contract=trace_contract,
            trace_version=str(trace.get("tested_version", "unspecified")),
            semantic_map=semantic_map,
        )
        if require_artifacts:
            baseline_binding(profile)
        return profile

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
        raise TimeoutError("telemetry collection exceeded its time budget")
    return min(30, remaining)


def _prometheus(profile: LiveProfile, query: str, start: float, end: float,
                deadline: float | None = None, annotations: list | None = None,
                family: str = "workload") -> list[dict]:
    data = _get_json(
        profile.metrics_url,
        "/api/v1/query_range",
        {"query": query, "start": start, "end": end, "step": f"{profile.query_step_seconds}s"},
        profile.metric_token_env, _remaining(deadline),
    )
    body = data.get("data")
    if data.get("status") != "success" or not isinstance(body, dict) or body.get("resultType") != "matrix":
        raise TelemetrySourceError("invalid Prometheus query_range response")
    result = body.get("result")
    if not isinstance(result, list) or any(not isinstance(series, dict) or not isinstance(series.get("metric"), dict)
                                         or not isinstance(series.get("values"), list) for series in result):
        raise TelemetrySourceError("invalid Prometheus series")
    for level in ("warnings", "infos"):
        messages = data.get(level, [])
        if not isinstance(messages, list) or any(not isinstance(x, str) for x in messages):
            raise TelemetrySourceError("invalid Prometheus query annotations")
        if annotations is not None:
            annotations.extend({"source": "metrics", "family": family, "level": level,
                                "message": message} for message in messages)
    return result


def baseline_issues(profile: LiveProfile, window: dict, status: dict,
                    start: float, end: float) -> list[str]:
    """Readiness concerns collection coverage, never model accuracy or labels."""
    issues = []
    if end - start < 60:
        issues.append("healthy interval must be at least 60 seconds")
    expected = math.floor((end - start) / profile.query_step_seconds) + 1
    points = {}
    for point in window.get("metrics", []):
        points.setdefault((point["service"], point["family"]), set()).add(point["timestamp"])
    sparse = [f"{service}/{family}" for service in profile.services for family in FAMILIES
              if len(points.get((service, family), ())) / expected < profile.baseline_min_coverage]
    if sparse:
        issues.append("insufficient returned metric-point coverage: " + ", ".join(sparse))
    if status.get("traces") != "available" or not window.get("traces"):
        issues.append("healthy trace source is unavailable or empty")
    observed = {span.get("service") for span in window.get("traces", [])}
    missing_traces = sorted(set(profile.services) - observed)
    if missing_traces:
        issues.append("healthy traces are missing for candidate services: " + ", ".join(missing_traces))
    if any(x["level"] == "warnings" for x in status.get("annotations", [])):
        issues.append("healthy metric source returned query warnings; inspect before preparation")
    return issues


def _jaeger_interval(profile: LiveProfile, service: str, left: float, right: float,
                     budget: list[int], deadline: float | None = None) -> list[dict]:
    """Split a saturated search instead of silently dropping traces at limit."""
    budget[0] -= 1
    if budget[0] < 0:
        raise TelemetrySourceError("trace search exceeded its request budget")
    if profile.trace_contract=="jaeger-v3-json":
        traces=decode_v3_stream(_get_payload(profile.traces_url,"/api/v3/traces",
            v3_query(service,left,right,TRACE_LIMIT),profile.trace_token_env,_remaining(deadline),v3_empty_search=True))
    else:
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


def _workload_intensity(series: list[dict], start: float, end: float) -> float:
    if len(series) != 1:
        raise TelemetrySourceError("workload query must return exactly one aggregated series")
    values, timestamps = [], set()
    for point in series[0].get("values", []):
        try:
            timestamp, value = map(float, point)
        except (TypeError, ValueError) as error:
            raise TelemetrySourceError("invalid workload observation") from error
        if not math.isfinite(timestamp) or not math.isfinite(value) or value < 0:
            raise TelemetrySourceError("non-finite or negative workload observation")
        if start <= timestamp <= end:
            if timestamp in timestamps:
                raise TelemetrySourceError("duplicate workload observation")
            timestamps.add(timestamp)
            values.append(value)
    if not values or sum(values) <= 0:
        raise TelemetrySourceError("positive workload intensity is unavailable for this interval")
    return sum(values) / len(values)


@_bounded_collection
def collect(profile: LiveProfile, start: float, end: float) -> tuple[dict, dict]:
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
        or not math.isfinite(start) or not math.isfinite(end)
        or start <= 0 or end <= start or end - start > MAX_WINDOW_SECONDS
    ):
        raise ApiError("INVALID_INTERVAL", "Задайте интервал в пределах одного часа: конец должен быть позже начала.",
                       fields=("start_unix", "end_unix"))
    if end > time.time():
        raise ApiError("INVALID_INTERVAL", "Конец интервала не может находиться в будущем.", fields=("end_unix",))
    metrics: list[dict] = []
    collected_at = time.time()
    annotations = []
    deadline = time.monotonic() + MAX_COLLECTION_SECONDS
    coverage = {service: set() for service in profile.services}
    seen_metric_points = set()
    point_counts = {(service, family): 0 for service in profile.services for family in FAMILIES}
    nonfinite = {family: 0 for family in FAMILIES}
    for family in FAMILIES:
        for series in _prometheus(profile, profile.metric_queries[family], start, end,
                                  deadline, annotations, family):
            labels = series.get("metric", {})
            name = labels.get(profile.metric_service_label)
            if not isinstance(name, str):
                raise TelemetrySourceError("metric series has no configured service label")
            try:
                service = profile.service(name)
            except ValueError as error:
                raise TelemetrySourceError("metric series contains an unmapped service") from error
            if service is None:
                continue
            for point in series.get("values", []):
                try:
                    timestamp, value = map(float, point)
                except (TypeError, ValueError) as error:
                    raise TelemetrySourceError("invalid metric point") from error
                if not math.isfinite(timestamp) or not math.isfinite(value):
                    nonfinite[family] += 1
                    continue
                if value < 0:
                    raise TelemetrySourceError(f"negative canonical {family} observation")
                if start <= timestamp <= end:
                    point = (timestamp, service, family)
                    if point in seen_metric_points:
                        raise TelemetrySourceError(
                            f"duplicate metric series for {service}/{family}; aggregate by service in the profile query"
                        )
                    seen_metric_points.add(point)
                    point_counts[(service, family)] += 1
                    metrics.append({
                        "timestamp": timestamp, "service": service, "family": family,
                        "value": value, "unit": CANONICAL_UNITS[family],
                    })
                    coverage[service].add(family)
    if not metrics:
        raise TelemetrySourceError("no metric observations for the configured candidates")
    metrics.sort(key=lambda item: (item["timestamp"], item["service"], item["family"]))
    for family, count in nonfinite.items():
        if count:
            annotations.append({"source": "metrics", "family": family, "level": "warnings",
                                "message": f"Excluded {count} non-finite metric points."})
    trace_accumulator = TraceAccumulator()
    trace_error = None
    try:
        budget = [MAX_TRACE_QUERIES]
        # A gateway-only query assumes perfect propagation. A new installation
        # can have disconnected traces; query every candidate's known source
        # names as well and deduplicate whole traces by ID before canonicalizing.
        query_services = sorted(set(profile.trace_query_services) | set(profile.services)
                                | set(profile.aliases))
        for entry_service in query_services:
            left = start
            while left < end:
                right = min(end, left + TRACE_CHUNK_SECONDS)
                for trace in _jaeger_interval(profile, entry_service, left, right, budget, deadline):
                    trace_accumulator.add(trace)
                left = right
        spans = canonicalize_jaeger({"data": trace_accumulator.data()})
        validate_canonical_spans(spans)
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
        workload = _prometheus(profile, profile.rps_query or "", start, end, deadline, annotations)
        rps = _workload_intensity(workload, start, end)
    if not math.isfinite(rps) or rps <= 0:
        raise TelemetrySourceError("invalid workload intensity")
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
        "metric_point_coverage": {
            service: {family: min(1.0, point_counts[(service, family)]
                                         / (math.floor((end - start) / profile.query_step_seconds) + 1))
                      for family in FAMILIES}
            for service in profile.services
        },
        "span_count": len(traces),
        "services_without_spans": sorted(set(profile.services) - {span["service"] for span in traces}),
        "annotations": annotations,
        "collected_at_unix": collected_at,
        "query_step_seconds": profile.query_step_seconds,
        "trace_api": profile.trace_contract,
        "trace_tested_version": profile.trace_version,
        "trace_query_services": query_services,
        "baseline_binding": baseline_binding(profile) if (profile.artifact_dir / "healthy-baseline.json").is_file() else {
            "state": "draft", "reason": "baseline_not_prepared"},
        "trace_search_completeness": "unknown_backend_search_depth_sampling_and_retention",
        "input_sha256": hashlib.sha256(json.dumps(
            window, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest(),
        "elapsed_seconds": round(time.monotonic() - deadline + MAX_COLLECTION_SECONDS, 4),
    }
    return window, status
