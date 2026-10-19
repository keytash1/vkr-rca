"""Optional, bounded HTTP observations. Never supplies ML features or ranks."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import multiprocessing
import os
from queue import Empty
from statistics import median
import time
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = "service-http-observations-v1"
CHANNELS = {
    "request_rate": ("requests_per_second", "per_second_completed_request_rate"),
    "error_ratio": ("ratio", "5xx_response_fraction_of_completed_requests"),
    "latency_p95": ("seconds", "histogram_estimated_p95_of_completed_server_requests"),
}
FAMILIES = {key: "http_" + key for key in CHANNELS}
MAX_SERVICES = 64
MAX_POINTS = 128
MAX_BYTES = 4 * 1024 * 1024


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"version", "queries", "source_presence_query", "lookback_seconds"} or config["version"] != VERSION:
        raise ValueError("invalid optional HTTP observation config")
    if type(config["lookback_seconds"]) is not int or not 1 <= config["lookback_seconds"] <= 3600:
        raise ValueError("HTTP lookback must be explicitly declared in seconds")
    queries = config["queries"]
    if not isinstance(queries, dict) or set(queries) != set(CHANNELS):
        raise ValueError("HTTP observations require rate, 5xx ratio and histogram p95")
    for channel, (unit, statistic) in CHANNELS.items():
        spec = queries[channel]
        if not isinstance(spec, dict) or set(spec) != {"query", "unit", "statistic"} or spec["unit"] != unit or spec["statistic"] != statistic:
            raise ValueError("HTTP unit/statistic differs from versioned contract")
        if not isinstance(spec["query"], str) or not spec["query"].strip() or len(spec["query"]) > 4096:
            raise ValueError("invalid HTTP metric query")
    presence = config["source_presence_query"]
    if not isinstance(presence, str) or not presence.strip() or len(presence) > 4096:
        raise ValueError("HTTP observations require per-service source presence")
    return config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _fetch(url, params, token_env, budget):
    headers = {"Accept": "application/json"}
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise ValueError("HTTP_SOURCE_CREDENTIAL_MISSING")
        headers["Authorization"] = "Bearer " + token
    limit = min(2 * 1024 * 1024, budget[0])
    if limit <= 0:
        raise ValueError("HTTP_SOURCE_BYTE_LIMIT")
    request = Request(url + "/api/v1/query_range?" + urlencode(params), headers=headers)
    with build_opener(_NoRedirect()).open(request, timeout=4) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("HTTP_SOURCE_BYTE_LIMIT")
    budget[0] -= len(payload)
    def invalid_constant(_):
        raise ValueError("HTTP_SOURCE_JSON_INVALID")
    return json.loads(payload, parse_constant=invalid_constant)


def decode_matrix(payload, scope, channel, start, end):
    """Only service, timestamp and scalar survive the source boundary."""
    if (not isinstance(payload, dict) or payload.get("status") != "success"
            or payload.get("warnings") or payload.get("infos")):
        raise ValueError("HTTP_SOURCE_ANNOTATION_OR_FAILURE")
    body = payload.get("data")
    if not isinstance(body, dict) or body.get("resultType") != "matrix" or not isinstance(body.get("result"), list):
        raise ValueError("HTTP_SOURCE_MATRIX_INVALID")
    if len(body["result"]) > MAX_SERVICES:
        raise ValueError("HTTP_SOURCE_SERIES_LIMIT")
    result = {}
    for row in body["result"]:
        if not isinstance(row, dict) or not isinstance(row.get("metric"), dict):
            raise ValueError("HTTP_SOURCE_SERIES_INVALID")
        source_name = row["metric"].get(scope["label"])
        if not isinstance(source_name, str):
            raise ValueError("HTTP_SOURCE_SERVICE_MISSING")
        if source_name in scope["ignored"]:
            continue
        service = scope["aliases"].get(source_name, source_name)
        if service not in scope["services"] or service in result:
            raise ValueError("HTTP_SOURCE_SERVICE_OR_AGGREGATION_INVALID")
        points = row.get("values")
        if not isinstance(points, list) or len(points) > MAX_POINTS:
            raise ValueError("HTTP_SOURCE_POINT_LIMIT")
        selected = {}
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or any(isinstance(x, bool) for x in point):
                raise ValueError("HTTP_SOURCE_POINT_INVALID")
            timestamp, value = map(float, point)
            if not math.isfinite(timestamp) or not start <= timestamp <= end or timestamp in selected:
                raise ValueError("HTTP_SOURCE_TIMESTAMP_INVALID")
            if math.isinf(value) or (math.isfinite(value) and (value < 0 or channel == "error_ratio" and value > 1)):
                raise ValueError("HTTP_SOURCE_VALUE_INVALID")
            if channel == "presence" and (not math.isfinite(value) or value not in (0, 1)):
                raise ValueError("HTTP_SOURCE_PRESENCE_INVALID")
            selected[timestamp] = value if math.isfinite(value) else None
        result[service] = selected
    return result


def summarize(matrices, services, start, end, step):
    expected = math.floor((end-start)/step) + 1
    for rows in matrices.values():
        for points in rows.values():
            if any(not math.isclose((stamp-start)/step, round((stamp-start)/step), abs_tol=1e-7, rel_tol=0)
                   for stamp in points):
                raise ValueError("HTTP_SOURCE_QUERY_GRID_INVALID")
    max_bins = max(4, min(64, 2048 // (len(services) * len(CHANNELS))))
    result = {}
    for service in services:
        presence = matrices["presence"].get(service, {})
        channels = {c: matrices[c].get(service, {}) for c in CHANNELS}
        rps = channels["request_rate"]
        if len(presence) != expected or any(v != 1 for v in presence.values()):
            state = "UNAVAILABLE"
        elif not rps or not any(v is not None for v in rps.values()):
            state = "INCOMPLETE"
        elif len(rps) == expected and all(v == 0 for v in rps.values()):
            state = "NO_ACTIVITY"
        else:
            active = {stamp for stamp, value in rps.items() if value is not None and value > 0}
            complete = len(rps) == expected and all(v is not None for v in rps.values()) and all(
                channels[c].get(stamp) is not None for c in ("error_ratio", "latency_p95") for stamp in active)
            state = "OBSERVED" if complete else "PARTIAL"
        rows = {}
        for channel, (unit, statistic) in CHANNELS.items():
            points = sorted((stamp, value) for stamp, value in channels[channel].items()
                            if value is not None and (channel == "request_rate" or (rps.get(stamp) or 0) > 0))
            channel_state = state
            if state in {"UNAVAILABLE", "INCOMPLETE"}:
                points = []
            elif state == "NO_ACTIVITY" and channel != "request_rate":
                points = []
                channel_state = "NOT_DEFINED_WITHOUT_TRAFFIC"
            values = [v for _, v in points]
            # Bin only for presentation, never for model inputs or global p95.
            width = max(1, math.ceil(len(points)/max_bins))
            bins = [{"start_unix": group[0][0], "end_unix": group[-1][0],
                     "min": min(v for _, v in group), "max": max(v for _, v in group),
                     "mean": sum(v for _, v in group)/len(group), "samples": len(group)}
                    for i in range(0, len(points), width) for group in [points[i:i+width]]]
            rows[channel] = {"family": FAMILIES[channel], "unit": unit, "statistic": statistic,
                "state": channel_state, "samples": len(values),
                "min": min(values) if values else None, "median": median(values) if values else None,
                "max": max(values) if values else None, "returned_point_coverage": len(values)/expected,
                "series": bins, "baseline_comparison": None, "model_input": False}
        result[service] = {"state": state, "metrics": rows}
    return {"version": VERSION, "status": "complete" if all(r["state"] in {"OBSERVED", "NO_ACTIVITY"} for r in result.values()) else "partial",
            "reason": "BOUNDED_HTTP_OBSERVATIONS", "services": result, "query_step_seconds": step,
            "start_unix": start, "end_unix": end,
            "collected_at_unix": time.time()}


def unavailable(services, reason, *, start, end):
    return {"version": VERSION, "status": "unavailable", "reason": reason,
            "services": {s: {"state": "UNAVAILABLE", "metrics": {}} for s in services},
            "start_unix": start, "end_unix": end,
            "collected_at_unix": time.time()}


def _worker(config, scope, start, end, results):
    try:
        step = max(scope["step"], math.ceil((end-start)/120))
        budget = [MAX_BYTES]
        queries = {c: config["queries"][c]["query"] for c in CHANNELS}
        queries["presence"] = config["source_presence_query"]
        matrices = {c: decode_matrix(_fetch(scope["url"], {"query": query, "start": start,
                    "end": end, "step": step}, scope["token_env"], budget), scope, c, start, end)
                    for c, query in queries.items()}
        results.put(summarize(matrices, scope["services"], start, end, step))
    except Exception:
        results.put(unavailable(scope["services"], "HTTP_SOURCE_INVALID_OR_UNAVAILABLE", start=start, end=end))


def collect_http(profile, start, end, *, timeout=5):
    config = profile.http_observations_config
    validate_config(config)
    if (not 0 < timeout <= 5 or len(profile.services) > MAX_SERVICES
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end))
            or not 0 < start < end <= time.time() or end-start > 3600):
        raise ValueError("HTTP observation collection exceeds scope")
    scope = {"services": profile.services, "aliases": profile.aliases,
             "ignored": profile.ignored_service_labels, "label": profile.metric_service_label,
             "url": profile.metrics_url, "token_env": profile.metric_token_env,
             "step": profile.query_step_seconds}
    context = multiprocessing.get_context("spawn")
    results = context.Queue(maxsize=1)
    worker = context.Process(target=_worker, args=(config, scope, start, end, results), daemon=True)
    worker.start()
    try:
        result = results.get(timeout=timeout)
        result["config_sha256"] = digest(config)
        result["lookback_seconds"] = config["lookback_seconds"]
        return result
    except Empty:
        result = unavailable(profile.services, "HTTP_SOURCE_DEADLINE_EXCEEDED", start=start, end=end)
        result["config_sha256"] = digest(config)
        result["lookback_seconds"] = config["lookback_seconds"]
        return result
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(.25)
        if worker.is_alive():
            worker.kill()
            worker.join(.25)
        results.close()
        results.join_thread()


def attach_http(catalog, profile, result):
    """Append facts without modifying original IDs, model outputs or core hash."""
    if ((result.get("start_unix"), result.get("end_unix")) != (catalog["start_unix"], catalog["end_unix"])
            or set(result["services"]) != set(catalog["services"]) or set(profile.services) != set(catalog["services"])):
        raise ValueError("HTTP observations do not belong to this analysis scope")
    config_hash = digest(profile.http_observations_config)
    if result.get("config_sha256", config_hash) != config_hash:
        raise ValueError("HTTP observation configuration differs from current profile")
    output = copy.deepcopy(catalog)
    summary = {"version": VERSION, "status": result["status"], "reason": result["reason"],
               "config_sha256": config_hash, "lookback_seconds": profile.http_observations_config["lookback_seconds"],
               "services": {s: row["state"] for s, row in result["services"].items()},
               "model_input": False, "collected_at_unix": result["collected_at_unix"]}
    output["catalog_version"] = "evidence-v4-service-http"
    output["source_quality"]["http_observations"] = summary
    output["limitations"] = list(dict.fromkeys(output["limitations"] + [
        "SERVICE_HTTP_OBSERVATIONS_SUPPLEMENTAL_NOT_MODEL_INPUT",
        "HTTP_P95_VALUES_ARE_TIME_LOCAL_ESTIMATES_NOT_GLOBAL_WINDOW_QUANTILE"]))
    for service in output["services"]:
        row = result["services"][service]
        for channel, (unit, statistic) in CHANNELS.items():
            value = copy.deepcopy(row["metrics"].get(channel, {"family": FAMILIES[channel],
                "unit": unit, "statistic": statistic, "state": row["state"], "samples": 0,
                "min": None, "median": None, "max": None, "returned_point_coverage": 0,
                "series": [], "baseline_comparison": None, "model_input": False}))
            value["query_lookback_seconds"] = summary["lookback_seconds"]
            fact = {"service": service, "kind": "metric", "start_unix": output["start_unix"],
                    "end_unix": output["end_unix"], "values": value}
            fact["id"] = "obs-" + digest({"http_config": summary["config_sha256"],
                "profile_id": output["profile_id"], "fact": fact})[:32]
            step = result.get("query_step_seconds", profile.query_step_seconds)
            fact["source_links"] = [{"kind": "prometheus_query_range", "url": profile.metrics_url +
                "/api/v1/query_range?" + urlencode({"query": profile.http_observations_config["queries"][channel]["query"],
                    "start": output["start_unix"], "end": output["end_unix"], "step": step})}]
            output["observations"].append(fact)
    return output
