"""One registered live RED pilot; immutable weights and separate oracle ledger."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / "rca-workbench"
sys.path[:0] = [str(ROOT / "ml"), str(PRODUCT / "cmd/thesis_demo")]
import numpy as np
from live_sources import LiveProfile, baseline_issues, collect
from profile_runtime import ProfileTransferRuntime
from rca_ml.m12_adapter import robust_baseline
from rca_ml.m13_features import fit_healthy_baseline
from rca_ml.m13_protocol import rank_scores, ranking_metrics, truth_rank
from rca_ml.r3_red import UNITS, evidence, fit_healthy, fuse

OUT = ROOT / "docs/product-research/r3-live-red-v1"
PRIVATE = ROOT / "artifacts/r3-live-red-v1"
SERVICES = ("gateway", "orders", "payment")
PORTS = {"gateway": 18680, "orders": 18681, "payment": 18682}
PATHS = {"gateway": "/api/order", "orders": "/orders/current", "payment": "/payments/authorize"}
PROM = "http://127.0.0.1:19990"
DOCKER = ["docker", "--host", "unix:///Users/maxryabets/.colima/default/docker.sock", "compose", "-f", str(ROOT / "deploy/acceptance/compose.yml")]
QUERY = json.loads((ROOT / "deploy/acceptance/red-queries.json").read_text())
UP = 'up{job="business-http-red",service=~"gateway|orders|payment"}'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def http(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    with urlopen(Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=20) as response:
        return json.load(response)


def query(expression, start=None, end=None):
    params = {"query": expression}
    endpoint = "query"
    if start is not None:
        endpoint = "query_range"; params |= {"start": start, "end": end, "step": 2}
    elif end is not None:
        params["time"] = end
    data = http(PROM + "/api/v1/" + endpoint + "?" + urlencode(params))
    if data.get("status") != "success" or data.get("warnings") or data.get("infos"):
        raise ValueError("query failed or has source annotations")
    return data["data"]["result"]


def red_window(start, end):
    observations = []
    raw = {}
    for channel, spec in QUERY["channels"].items():
        raw[channel] = query(spec["query"], start, end)
        seen = set()
        for series in raw[channel]:
            service = series["metric"]["service"]
            if service not in SERVICES or service in seen:
                raise ValueError("RED identity or aggregation mismatch")
            seen.add(service)
            for timestamp, value in series["values"]:
                number = float(value)
                observations.append({"service": service, "channel": channel, "unit": UNITS[channel],
                    "timestamp": timestamp, "value": number if math.isfinite(number) else None})
    raw["up"] = query(UP, start, end)
    states = dict.fromkeys(SERVICES, "unknown")
    for series in raw["up"]:
        service = series["metric"]["service"]
        if service not in SERVICES or states[service] != "unknown":
            raise ValueError("scrape target universe differs")
        points = series["values"]
        expected = math.floor((end-start)/2)+1
        states[service] = "available" if len(points) == expected and all(float(v) == 1 for _, v in points) else "unavailable"
    return observations, states, raw


def reset():
    for service in SERVICES:
        http(f"http://127.0.0.1:{PORTS[service]}/debug/reset", {})


def wait_until(deadline):
    while time.time() < deadline:
        time.sleep(min(1, deadline-time.time()))


def compose(*args):
    subprocess.run(DOCKER + list(args), check=True, timeout=45, capture_output=True)


def run():
    OUT.mkdir(exist_ok=False); PRIVATE.mkdir(parents=True, exist_ok=False)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("registered 15 minute budget")))
    signal.alarm(900)
    cases = [{"id": f"g-{i+1:03}", "root_service": service, "fault_family": mechanism}
             for i, (service, mechanism) in enumerate((s, m) for s in SERVICES for m in ("latency", "error"))]
    protected = json.loads((ROOT / "docs/product-research/r3-new-corpus-v1/overlap-and-protected.json").read_text())["protected_assets_sha256"]
    for path, expected in protected.items():
        if sha(ROOT/path) != expected: raise ValueError("protected asset changed: " + path)
    save(OUT/"registration.json", {"protocol_sha256": sha(ROOT/"docs/R3_LIVE_RED_PROTOCOL.md"),
        "script_sha256": sha(__file__), "red_code_sha256": sha(ROOT/"ml/rca_ml/r3_red.py"),
        "query_sha256": sha(ROOT/"deploy/acceptance/red-queries.json"), "cases_evaluation_only": cases,
        "services": SERVICES, "ranker_fits": 0, "rrf_k": 60, "role": "CONTROLLED_EXPLORATORY_PILOT_NOT_TEST",
        "research_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "product_head": subprocess.check_output(["git", "-C", str(PRODUCT), "rev-parse", "HEAD"], text=True).strip(),
        "protected_assets_sha256": protected})
    raw_profile = json.loads((ROOT/"deploy/acceptance/profiles/local-three.json").read_text())
    raw_profile["id"] = "r3-live-red-v1"; raw_profile["artifact_dir"] = str((PRIVATE/"baseline").relative_to(ROOT))
    profile_path = PRIVATE/"profile.json"; save(profile_path, raw_profile)
    profile = LiveProfile.load(profile_path, ROOT, require_artifacts=False)
    workload_was_stopped = payment_was_stopped = False
    try:
        reset()
        start = int(time.time()) + 3; end = start + 70
        print("healthy capture 70s", start, end, flush=True); wait_until(end+5)
        healthy_window, healthy_status = collect(profile, start, end)
        save(PRIVATE/"healthy-window.json", healthy_window); save(PRIVATE/"healthy-status.json", healthy_status)
        issues = baseline_issues(profile, healthy_window, healthy_status, start, end)
        if issues: raise ValueError("healthy preflight: " + "; ".join(issues))
        for name in ("failed", "dropped"):
            response = query(f"sum(increase(acceptance_requests_{name}_total[70s]))", end=end)
            if len(response) != 1 or float(response[0]["value"][1]) != 0:
                raise ValueError("healthy workload failed/dropped")
        healthy_red, healthy_sources, raw = red_window(start, end)
        if set(healthy_sources.values()) != {"available"}: raise ValueError("healthy RED scrape incomplete")
        save(PRIVATE/"healthy-red.json", raw)
        healthy = {"segments": [{"start_unix": start, "end_unix": end, "requests_per_second": healthy_window["requests_per_second"]}],
                   "metrics": healthy_window["metrics"], "traces": healthy_window["traces"]}
        save(PRIVATE/"baseline/healthy-baseline.json", fit_healthy_baseline(healthy, SERVICES))
        save(PRIVATE/"baseline/legacy-metric-baseline.json", robust_baseline(healthy_window["metrics"]))
        red_baseline = fit_healthy(healthy_red, SERVICES); save(PRIVATE/"baseline/red-baseline.json", red_baseline)
        runtime = ProfileTransferRuntime(ROOT, PRIVATE/"baseline", SERVICES)
        profile = LiveProfile.load(profile_path, ROOT)
        # Same target scope and explicit historical evaluation time.
        counters = query("sum by(service) (rca_http_server_requests_total)", end=end)
        counts = query("rca_http_server_request_duration_seconds_count", end=end)
        infinity = query('rca_http_server_request_duration_seconds_bucket{le="+Inf"}', end=end)
        def mapping(rows): return {r["metric"]["service"]: float(r["value"][1]) for r in rows}
        if mapping(counters) != mapping(counts) or mapping(counts) != mapping(infinity):
            raise ValueError("counter/histogram denominators differ")
        save(OUT/"preflight.json", {"source_states": healthy_sources, "counter_count_inf_equal": True,
            "counts": mapping(counts), "healthy_start": start, "healthy_end": end,
            "metric_samples": len(healthy_window["metrics"]), "span_count": len(healthy_window["traces"]),
            "prometheus_build": http(PROM+"/api/v1/status/buildinfo")["data"]})
        outcomes = []; truths = {}; predictions = {mode: {v: {} for v in ("frozen_m13", "resource_heuristic", "red_heuristic", "rrf")}
                                                for mode in ("observed_traces", "no_traces")}
        for case in cases:
            reset()
            service, mechanism, name = case["root_service"], case["fault_family"], case["id"]
            control = {"latency_ms": 200 if mechanism == "latency" else 0, "error_rate": 1 if mechanism == "error" else 0}
            http(f"http://127.0.0.1:{PORTS[service]}/debug/fault", control)
            start = int(time.time()) + 35; end = start + 35
            print(name, "warm/measure", service, mechanism, start, end, flush=True); wait_until(end+5)
            window, source = collect(profile, start, end)
            records, sources, red_raw = red_window(start, end)
            save(PRIVATE/f"{name}/window.json", window); save(PRIVATE/f"{name}/source.json", source)
            save(PRIVATE/f"{name}/red.json", red_raw)
            red = evidence(records, red_baseline, SERVICES, sources)
            # Capture persisted first; oracle checks are separate and after interval.
            began = time.monotonic()
            try:
                with urlopen(f"http://127.0.0.1:{PORTS[service]}{PATHS[service]}", timeout=4) as response:
                    code = response.status; response.read(1024*1024)
            except HTTPError as error:
                code = error.code; error.close()
            elapsed = time.monotonic()-began
            root_channel = "latency_p95" if mechanism == "latency" else "error_ratio"
            root_values = [r["value"] for r in records if r["service"] == service and r["channel"] == root_channel and r["value"] is not None]
            effect = (code == 200 and elapsed >= .18 and root_values and float(np.median(root_values)) >= .15) if mechanism == "latency" else (
                code == 500 and root_values and float(np.median(root_values)) >= .9)
            valid = bool(effect) and set(sources.values()) == {"available"} and source["traces"] == "available" and bool(window["traces"])
            detail = {"id": name, "valid": valid, "root_http_code": code, "root_elapsed_seconds": elapsed,
                      "red": red, "source_states": sources, "observed_spans": len(window["traces"]), "root_ranks": {}}
            for mode in predictions:
                current = copy.deepcopy(window)
                if mode == "no_traces": current["traces"] = []; current["traces_collected"] = False
                result = runtime.rank_all(current)
                methods = {"frozen_m13": result["frozen_m13"], "resource_heuristic": result["metric_heuristic"],
                           "red_heuristic": rank_scores(red["scores"]), "rrf": fuse(result["frozen_m13"], red)}
                detail["root_ranks"][mode] = {method: truth_rank(ranking, service) for method, ranking in methods.items()}
                for method, ranking in methods.items(): predictions[mode][method][name] = ranking
            truths[name] = {"root_service": service, "fault_family": mechanism, "system": "local-three-new-red"}
            outcomes.append(detail)
            save(OUT/f"{name}.json", detail)
            print(name, "valid", valid, "ranks", detail["root_ranks"], flush=True)
        reset()
        compose("stop", "workload"); workload_was_stopped = True
        wait_until(time.time()+40)
        idle_records, idle_sources, idle_raw = red_window(int(time.time())-4, int(time.time()))
        idle = evidence(idle_records, red_baseline, SERVICES, idle_sources)
        save(PRIVATE/"idle-red.json", idle_raw)
        if set(idle["states"].values()) != {"no_activity"}: raise ValueError("idle control was not observed as no_activity")
        compose("stop", "payment"); payment_was_stopped = True
        wait_until(time.time()+7)
        outage_end = int(time.time()); outage_records, outage_sources, outage_raw = red_window(outage_end-4, outage_end)
        outage = evidence(outage_records, red_baseline, SERVICES, outage_sources)
        save(PRIVATE/"outage-red.json", outage_raw)
        if outage["states"]["payment"] != "source_unavailable": raise ValueError("outage became a normal zero")
        for path, expected in protected.items():
            if sha(ROOT/path) != expected: raise ValueError("protected asset changed")
        save(OUT/"predictions.json", {"truth_evaluation_only": truths, "predictions": predictions})
        save(OUT/"results.json", {"role": "CONTROLLED_EXPLORATORY_PILOT_NOT_TEST", "cases": len(outcomes),
            "valid_cases": sum(c["valid"] for c in outcomes), "promotion_allowed": False,
            "metrics_all_six_including_invalid": {mode: {method: ranking_metrics(ranking, truths) for method, ranking in methods.items()}
                                                 for mode, methods in predictions.items()},
            "idle": idle, "outage": outage, "ranker_fits": 0, "protected_assets_unchanged": True})
        print("completed pilot; no model promoted", flush=True)
    finally:
        signal.alarm(0)
        if payment_was_stopped:
            compose("start", "payment")
            ready_deadline = time.monotonic()+15
            while True:
                try:
                    http(f"http://127.0.0.1:{PORTS['payment']}/health")
                    break
                except OSError:
                    if time.monotonic() >= ready_deadline: raise
                    time.sleep(.25)
        try:
            reset()
        finally:
            if workload_was_stopped: compose("start", "workload")


if __name__ == "__main__": run()
