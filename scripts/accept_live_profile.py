"""Exercise a real installed telemetry profile without measuring model accuracy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]

from live_sources import LiveProfile, collect
from profile_check import check_profile
from profile_setup import prepare
from server import DiagnosticApplication, make_handler


def request(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urlopen(Request(url, data=body, headers=headers), timeout=150) as response:
        return json.load(response)


def save(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def verify_healthy_workload(responses: dict) -> dict[str, float]:
    """Missing counters are unknown, never evidence of zero failed requests."""
    values = {}
    for name in ("started", "succeeded", "failed", "dropped"):
        response = responses.get(name, {})
        try:
            results = response["data"]["result"]
            if response["status"] != "success" or len(results) != 1:
                raise ValueError("expected exactly one counter result")
            value = float(results[0]["value"][1])
            if not math.isfinite(value) or value < 0:
                raise ValueError("invalid counter increase")
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"healthy workload cannot be verified: counter '{name}' is missing or invalid; "
                "check the workload exporter and choose a fully observed interval"
            ) from error
        values[name] = value
    if values["failed"] > 0 or values["dropped"] > 0 or min(values["started"], values["succeeded"]) <= 0:
        raise RuntimeError("selected healthy interval includes failed/dropped requests or no successful workload")
    return values


def run(profile_path: Path, output: Path, *, verify_workload: bool = False) -> None:
    profile_path = profile_path.resolve()
    output.mkdir(parents=True, exist_ok=False)
    profile = LiveProfile.load(profile_path, ROOT, require_artifacts=False)
    now = int(time.time()) // profile.query_step_seconds * profile.query_step_seconds
    healthy_start, healthy_end = now - 210, now - 80
    start, end = now - 60, now - 20
    times = {"healthy_start": healthy_start, "healthy_end": healthy_end,
             "start_unix": start, "end_unix": end}
    save(output / "intervals.json", times)
    if verify_workload:
        health = {}
        for name in ("started", "succeeded", "failed", "dropped"):
            expression = f"sum(increase(acceptance_requests_{name}_total[{healthy_end - healthy_start}s]))"
            health[name] = request(profile.metrics_url + "/api/v1/query?" + urlencode({
                "query": expression, "time": healthy_end,
            }))
        save(output / "workload-health.json", health)
        verify_healthy_workload(health)
    preflight = check_profile(ROOT, profile_path, healthy_start, healthy_end, baseline=True)
    save(output / "preflight.json", preflight)
    if preflight["verdict"] != "ready":
        raise RuntimeError("real sources are not ready for healthy baseline; see preflight.json")
    baseline_reused = profile.artifact_dir.exists()
    if not baseline_reused:
        provenance = prepare(ROOT, profile_path, healthy_start, healthy_end)
    else:
        provenance = json.loads((profile.artifact_dir / "provenance.json").read_text())
    save(output / "baseline-provenance.json", provenance)
    window, source = collect(profile, start, end)
    save(output / "canonical-window.json", window)
    save(output / "source-status.json", source)
    # Independent raw response checks, outside the collection implementation.
    for family, expression in profile.metric_queries.items():
        raw = request(profile.metrics_url + "/api/v1/query_range?" + urlencode({
            "query": expression, "start": start, "end": end, "step": str(profile.query_step_seconds),
        }))
        raw_services = sorted(filter(None, (profile.service(item["metric"][profile.metric_service_label])
                              for item in raw["data"]["result"])))
        if raw_services != list(profile.services):
            raise RuntimeError(f"direct {family} response differs from profile candidates")
        canonical = {(p["service"], p["timestamp"]): p["value"]
                     for p in window["metrics"] if p["family"] == family}
        expected_points = {}
        for series in raw["data"]["result"]:
            service = profile.service(series["metric"][profile.metric_service_label])
            if service is not None:
                expected_points.update({(service, float(timestamp)): float(value) for timestamp, value in series["values"]})
        if canonical != expected_points:
            raise RuntimeError(f"canonical {family} differs from direct source")
        save(output / f"raw-{family}-response.json", raw)
    canonical_spans = {(p["trace_id"], p["span_id"]) for p in window["traces"]}
    direct_counts = {}
    for service in profile.services:
        raw = request(profile.traces_url + "/api/traces?" + urlencode({
            "service": service, "start": int(start * 1_000_000), "end": int(end * 1_000_000), "limit": 1000,
        }))
        if len(raw["data"]) >= 1000:
            raise RuntimeError("direct trace comparison saturated; choose a shorter acceptance interval")
        direct = {(str(span["traceID"]), str(span["spanID"])) for trace in raw["data"] for span in trace["spans"]}
        if not direct or not direct.issubset(canonical_spans):
            raise RuntimeError(f"canonical traces miss directly observed candidate spans: {service}")
        direct_counts[service] = len(direct)
        save(output / f"raw-traces-{service}.json", raw)
    app = DiagnosticApplication(ROOT, profile_path.parent)
    offline = app.analyze(window, app.profile_runtimes[profile.id])
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = request(f"http://127.0.0.1:{server.server_port}/api/analyze", {
            "profile_id": profile.id, "start_unix": start, "end_unix": end,
        })
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    save(output / "live-result.json", result)
    expected = [(x["service"], x["rank"], x["model_score"]) for x in offline["candidates"]]
    actual = [(x["service"], x["rank"], x["model_score"]) for x in result["candidates"]]
    if actual != expected:
        raise RuntimeError("live/replay differs; inspect late source data before acceptance")
    if sorted(x["service"] for x in result["candidates"]) != list(profile.services):
        raise RuntimeError("incomplete result candidates")
    if result["source_status"]["traces"] != "available" or not result["source_status"]["span_count"]:
        raise RuntimeError("real trace collection was not confirmed")
    if "root_service" in result:
        raise RuntimeError("unexpected evaluation label in product response")
    summary = {
        "status": "PASSED_API_REAL_SOURCES_BROWSER_PENDING",
        "purpose": "ENGINEERING_INTEGRATION_NO_ACCURACY_EVALUATION",
        "profile_id": profile.id, "profile_version": profile.version,
        "candidate_services": list(profile.services),
        "trace_api": profile.trace_contract, "trace_tested_version": profile.trace_version,
        "intervals": times, "source_status": source,
        "direct_cpu_values_match": True, "all_metric_families_match": True,
        "direct_candidate_span_ids_present": direct_counts, "replay_scores_match": True,
        "baseline_reused": baseline_reused,
        "baseline_interval": {"start_unix": provenance["healthy_start_unix"], "end_unix": provenance["healthy_end_unix"]},
        "model_version": result["model_version"],
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save(output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "output": str(output),
                      "candidates": len(profile.services), "spans": source["span_count"],
                      "intervals": times}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-workload", action="store_true",
                        help="Require real acceptance workload to show successful requests and no failures/drops during the healthy interval")
    args = parser.parse_args()
    run(args.profile, args.output, verify_workload=args.verify_workload)
