#!/usr/bin/env python3
"""M13 deployment readiness, healthy baseline, canaries and development corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from rca_ml.dataset import sha256_file  # noqa: E402
from rca_ml.m13_trace import canonicalize_jaeger  # noqa: E402
from rca_ml.m12_adapter import CANONICAL_UNITS  # noqa: E402

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/m13/compose.yml")]
FRONTEND_URL = os.getenv("M13_FRONTEND_URL", "http://127.0.0.1:15013")
PROMETHEUS_URL = os.getenv("M13_PROMETHEUS_URL", "http://127.0.0.1:19091")
JAEGER_URL = os.getenv("M13_JAEGER_URL", "http://127.0.0.1:16688")
RUN_DIR = ROOT / "external-data/m13/runs/development-v1"
SERVICES = [
    "nginx-thrift", "social-graph-service", "compose-post-service", "post-storage-service",
    "user-timeline-service", "url-shorten-service", "user-service", "media-service",
    "text-service", "unique-id-service", "user-mention-service", "home-timeline-service",
]
TARGETS = [
    "compose-post-service", "post-storage-service", "user-timeline-service",
    "url-shorten-service", "text-service", "user-mention-service",
]
FAULTS = ["cpu", "memory", "network_latency", "packet_loss", "service_unavailable"]
REGIMES = {"mixed_low": 6, "mixed_high": 9}
QUERIES = {
    "cpu": "m13_container_cpu_cores",
    "memory": "m13_container_memory_working_set_bytes",
    "network": "rate(m13_container_network_receive_bytes_total[5s]) + rate(m13_container_network_transmit_bytes_total[5s])",
    "traffic_rate": "rate(m13_container_network_receive_bytes_total[5s])",
}


def command(*args: str, check: bool = True, capture: bool = False):
    return subprocess.run([*COMPOSE, *args], cwd=ROOT, check=check, text=True, capture_output=capture)


def ready() -> dict:
    started = time.time()
    deadline = started + 300
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(FRONTEND_URL + "/", timeout=3) as response:
                if response.status == 200:
                    break
        except Exception as error:
            last = str(error)
        time.sleep(2)
    else:
        raise RuntimeError(f"Social Network readiness timeout: {last}")
    while time.time() < deadline:
        metrics = prom('up{job="m13-container-metrics"}')
        if metrics and float(metrics[0]["value"][1]) == 1:
            break
        time.sleep(2)
    else:
        raise RuntimeError("M13 Prometheus readiness timeout")
    initialization_result = {}
    while time.time() < deadline:
        initialization = subprocess.run(
            [sys.executable, str(ROOT / "scripts/m13/workload.py"), "--init"],
            cwd=ROOT, check=True, text=True, capture_output=True,
        )
        initialization_result = json.loads(initialization.stdout)
        failed_registrations = {
            status: count for status, count in initialization_result["statuses"].items()
            if int(status) == 0 or int(status) >= 500
        }
        failed_follows = {
            status: count for status, count in initialization_result["follow_statuses"].items()
            if int(status) == 0 or int(status) >= 500
        }
        if not failed_registrations and not failed_follows:
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"M13 graph initialization timeout: registrations={failed_registrations}, follows={failed_follows}")
    result = {"ready_seconds": time.time()-started, "initialization": initialization_result}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "readiness.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return result


def prom(query: str, start: float | None = None, end: float | None = None) -> list[dict]:
    endpoint = "/api/v1/query_range" if start is not None else "/api/v1/query"
    params = {"query": query}
    if start is not None:
        params.update({"start": str(start), "end": str(end), "step": "1s"})
    url = PROMETHEUS_URL + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    if payload["status"] != "success":
        raise RuntimeError(payload)
    return payload["data"]["result"]


def collect_metrics(start: float, end: float) -> list[dict]:
    output = []
    for family, query in QUERIES.items():
        for series in prom(query, start, end):
            service = series["metric"].get("service")
            if service not in SERVICES:
                continue
            for timestamp, value in series.get("values", []):
                output.append({
                    "timestamp": int(float(timestamp)), "service": service, "family": family,
                    "value": float(value), "unit": CANONICAL_UNITS[family],
                })
    output.sort(key=lambda item: (item["timestamp"], item["service"], item["family"]))
    return output


def collect_traces(start: float, end: float) -> tuple[list[dict], bool]:
    traces: dict[str, dict] = {}
    left = start
    try:
        while left < end:
            right = min(end, left+30)
            params = urllib.parse.urlencode({
                "service": "nginx-thrift", "start": int(left*1_000_000),
                "end": int(right*1_000_000), "limit": 2000,
            })
            with urllib.request.urlopen(JAEGER_URL + "/api/traces?"+params, timeout=30) as response:
                payload = json.load(response)
            for trace in payload.get("data", []):
                traces[str(trace["traceID"])] = trace
            left = right
    except Exception:
        return [], False
    return canonicalize_jaeger({"data": list(traces.values())}), True


def workload_thread(duration: float, regime: str, seed: int):
    result = {}
    def target():
        proc = subprocess.run([
            sys.executable, str(ROOT / "scripts/m13/workload.py"), "--duration", str(duration),
            "--regime", regime, "--seed", str(seed),
        ], cwd=ROOT, text=True, capture_output=True)
        result.update({"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()})
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result


def validate_workload(result: dict, *, phase: str, allow_injected_failures: bool = False) -> dict:
    if result.get("returncode") != 0 or not result.get("stdout"):
        raise RuntimeError(f"M13 {phase} workload process failed: {result}")
    payload = json.loads(result["stdout"])
    failures = sum(count for status, count in payload["statuses"].items() if int(status) == 0 or int(status) >= 500)
    if failures and not allow_injected_failures:
        raise RuntimeError(f"M13 {phase} workload has {failures}/{payload['attempts']} transport/server failures: {payload['statuses']}")
    if payload["attempts"] <= 0 or payload["dispatch_rate"] < .99 * payload["requests_per_second"]:
        raise RuntimeError(f"M13 {phase} did not sustain its dispatch contract: {payload}")
    return payload


def healthy(warmup: int, baseline_seconds: int) -> dict:
    warm, warm_result = workload_thread(warmup, "mixed_low", 20260906)
    warm.join()
    validate_workload(warm_result, phase="warm-up")
    half = baseline_seconds // 2
    segments, workload_results = [], []
    overall_start = time.time()
    for offset, regime in enumerate(("mixed_low", "mixed_high")):
        start = time.time()
        thread, result = workload_thread(half, regime, 20260907+offset)
        thread.join()
        validate_workload(result, phase=regime)
        end = time.time()
        segments.append({"start_unix": start, "end_unix": end, "workload_regime": regime, "requests_per_second": REGIMES[regime]})
        workload_results.append(result)
    overall_end = time.time()
    time.sleep(3)
    metrics = collect_metrics(overall_start, overall_end)
    traces, collected = collect_traces(overall_start, overall_end)
    if not collected or not traces:
        raise RuntimeError("healthy Jaeger traces unavailable")
    coverage = {(item["service"], item["family"]) for item in metrics}
    missing = [(service, family) for service in SERVICES for family in QUERIES if (service, family) not in coverage]
    if missing:
        raise RuntimeError(f"healthy metric coverage incomplete: {missing}")
    output = {
        "role": "M13_HEALTHY_ENGINEERING", "warmup_seconds": warmup,
        "baseline_seconds": baseline_seconds, "scrape_interval_seconds": 1,
        "trace_sampling": 1.0, "segments": segments, "metrics": metrics, "traces": traces,
        "traces_collected": collected, "warmup_result": warm_result,
        "baseline_workload_results": workload_results,
        "protocol_deviations": (["warm-up below preferred 300 seconds"] if warmup < 300 else [])
            + (["baseline below preferred 900 seconds"] if baseline_seconds < 900 else []),
    }
    path = RUN_DIR / "healthy"; path.mkdir(parents=True, exist_ok=True)
    (path / "baseline.json").write_text(json.dumps(output, separators=(",", ":")))
    return {"metrics": len(metrics), "spans": len(traces), "segments": segments, "deviations": output["protocol_deviations"]}


def container_id(service: str) -> str:
    ids = command("ps", "-q", service, capture=True).stdout.strip().splitlines()
    if len(ids) != 1:
        raise RuntimeError(f"expected one container for {service}, got {ids}")
    return ids[0]


def netem(service: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([
        "docker", "run", "--rm", "--network", f"container:{container_id(service)}",
        "--cap-add", "NET_ADMIN", "vkr-rca-m13/fault-tool:v1", *args,
    ], cwd=ROOT, text=True, capture_output=True, check=check)


def inject(service: str, fault: str, duration: int) -> dict:
    if fault == "cpu":
        proc = command("exec", "-T", "-d", service, "timeout", str(duration), "dd", "if=/dev/zero", "of=/dev/null", "bs=1M", capture=True)
        criterion = "target CPU robustly exceeds healthy CPU"
    elif fault == "memory":
        proc = command("exec", "-T", "-d", service, "perl", "-e", f"$x='x' x 134217728; sleep {duration}", capture=True)
        criterion = "target working set exceeds healthy median by 64 MiB"
    elif fault == "network_latency":
        proc = netem(service, "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", "200ms")
        criterion = "target netns qdisc reports 200ms delay"
    elif fault == "packet_loss":
        proc = netem(service, "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", "15%")
        criterion = "target netns qdisc reports 15% loss"
    elif fault == "service_unavailable":
        proc = command("pause", service, capture=True)
        criterion = "Docker reports target paused"
    else:
        raise ValueError(fault)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "criterion": criterion}


def mechanism_state(service: str, fault: str) -> str:
    if fault in {"network_latency", "packet_loss"}:
        return netem(service, "qdisc", "show", "dev", "eth0").stdout.strip()
    if fault == "service_unavailable":
        return subprocess.run(["docker", "inspect", "-f", "{{.State.Paused}}", container_id(service)], check=True, text=True, capture_output=True).stdout.strip()
    process = "dd" if fault == "cpu" else "perl"
    return command("exec", "-T", service, "pgrep", "-a", process, check=False, capture=True).stdout.strip()


def reset_fault(service: str, fault: str) -> None:
    if fault in {"network_latency", "packet_loss"}:
        netem(service, "qdisc", "del", "dev", "eth0", "root", check=False)
    elif fault == "service_unavailable":
        command("unpause", service, check=False, capture=True)
    else:
        command("exec", "-T", service, "pkill", "dd" if fault == "cpu" else "perl", check=False, capture=True)
        if fault == "cpu":
            command("exec", "-T", service, "pkill", "timeout", check=False, capture=True)


def valid_injection(service: str, fault: str, state: str, metrics: list[dict], healthy_data: dict) -> bool:
    if fault == "network_latency": return "delay 200ms" in state
    if fault == "packet_loss": return "loss 15%" in state
    if fault == "service_unavailable": return state == "true"
    family = "cpu" if fault == "cpu" else "memory"
    observed = [item["value"] for item in metrics if item["service"] == service and item["family"] == family]
    normal = [item["value"] for item in healthy_data["metrics"] if item["service"] == service and item["family"] == family]
    if not observed or not normal: return False
    return max(observed) > (float(np.quantile(normal, .9)) + (.10 if fault == "cpu" else 64*1024*1024))


def capture_case(case: dict, duration: int, seed: int) -> tuple[dict, dict]:
    service, fault, regime = case["root_service"], case["fault_family"], case["workload_regime"]
    start = time.time()
    thread, workload = workload_thread(duration, regime, seed)
    injected = False
    try:
        injection = inject(service, fault, duration)
        injected = True
        time.sleep(2)
        state = mechanism_state(service, fault)
        thread.join()
        validate_workload(workload, phase=f"incident {case['incident_id']}", allow_injected_failures=True)
    finally:
        if injected:
            reset_fault(service, fault)
        if thread.is_alive():
            thread.join(timeout=5)
    end = time.time()
    time.sleep(2)
    metrics = collect_metrics(start, end)
    traces, trace_collected = collect_traces(start, end)
    telemetry = {
        "incident_id": case["incident_id"], "start_unix": start, "end_unix": end,
        "requests_per_second": REGIMES[regime], "candidate_services": SERVICES,
        "metrics": metrics, "traces": traces, "traces_collected": trace_collected,
        "workload_result": workload,
    }
    truth = {**case, "injection_evidence": {"returncode": injection["returncode"], "state": state}}
    return telemetry, truth


def canary(duration: int) -> dict:
    healthy_data = json.loads((RUN_DIR / "healthy/baseline.json").read_text())
    results = []
    for index, fault in enumerate(FAULTS):
        case = {"incident_id": f"m13-canary-{fault}", "root_service": "compose-post-service", "fault_family": fault, "workload_regime": "mixed_low", "intensity": intensity(fault)}
        telemetry, truth = capture_case(case, duration, 20261000+index)
        valid = valid_injection(case["root_service"], fault, truth["injection_evidence"]["state"], telemetry["metrics"], healthy_data)
        results.append({"fault_family": fault, "valid": valid, "evidence": truth["injection_evidence"], "spans": len(telemetry["traces"]), "rankings_generated": False})
    output = {"role": "M13_CANARY", "rankings_generated": False, "results": results}
    path = RUN_DIR / "canary"; path.mkdir(parents=True, exist_ok=True)
    (path / "validity.json").write_text(json.dumps(output, indent=2, sort_keys=True)+"\n")
    if not all(item["valid"] for item in results):
        raise RuntimeError("M13 canary gate failed")
    return output


def intensity(fault: str) -> str:
    return {"cpu": "one_worker", "memory": "128MiB", "network_latency": "200ms", "packet_loss": "15pct", "service_unavailable": "paused"}[fault]


def plan() -> dict:
    cases = [
        {"root_service": service, "fault_family": fault, "workload_regime": regime, "intensity": intensity(fault), "repetition": repetition}
        for service in TARGETS for fault in FAULTS for regime in REGIMES for repetition in (1, 2)
    ]
    random.Random(20260906).shuffle(cases)
    for index, case in enumerate(cases, 1):
        digest = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:8]
        case["incident_id"] = f"m13-{index:03d}-{digest}"
    return {"version": "m13-plan-v1", "seed": 20260906, "incidents": cases, "clusters": 60, "repetitions_per_cluster": 2}


def corpus(duration: int) -> dict:
    healthy_data = json.loads((RUN_DIR / "healthy/baseline.json").read_text())
    canary_data = json.loads((RUN_DIR / "canary/validity.json").read_text())
    if canary_data["rankings_generated"] or not all(item["valid"] for item in canary_data["results"]):
        raise RuntimeError("canary gate not satisfied")
    planned = plan()
    plan_path = ROOT / "ml/models/m13/incident-plan.json"
    plan_path.write_text(json.dumps(planned, indent=2, sort_keys=True)+"\n")
    telemetry_dir = RUN_DIR / "telemetry"; telemetry_dir.mkdir(parents=True, exist_ok=True)
    progress_truth = RUN_DIR / "truth.progress.jsonl"
    progress_index = RUN_DIR / "telemetry-index.progress.jsonl"
    truth = [json.loads(line) for line in progress_truth.read_text().splitlines() if line] if progress_truth.exists() else []
    index = [json.loads(line) for line in progress_index.read_text().splitlines() if line] if progress_index.exists() else []
    completed = {item["incident_id"] for item in truth}
    if completed != {item["incident_id"] for item in index} or not completed <= {item["incident_id"] for item in planned["incidents"]}:
        raise RuntimeError("M13 resume checkpoint does not match the frozen incident plan")
    replacements = sum(int(item.get("collection_attempt", 1)) - 1 for item in truth)
    for position, case in enumerate(planned["incidents"], 1):
        if case["incident_id"] in completed:
            print(f"M13 corpus {position}/{len(planned['incidents'])} {case['incident_id']} resumed", flush=True)
            continue
        for attempt in (1, 2):
            telemetry, truth_item = capture_case(case, duration, 20260906+position*10+attempt)
            valid = valid_injection(case["root_service"], case["fault_family"], truth_item["injection_evidence"]["state"], telemetry["metrics"], healthy_data)
            truth_item["valid_injection"] = valid
            if valid:
                break
            replacements += 1
        if not valid:
            raise RuntimeError(f"M13 case failed after one replacement: {case['incident_id']}")
        path = telemetry_dir / f"{case['incident_id']}.json"
        path.write_text(json.dumps(telemetry, separators=(",", ":")))
        truth_item["collection_attempt"] = attempt
        truth.append(truth_item)
        index.append({"incident_id": case["incident_id"], "telemetry_path": str(path.relative_to(RUN_DIR)), "sha256": sha256_file(path)})
        progress_truth.write_text("".join(json.dumps(item, sort_keys=True)+"\n" for item in truth))
        progress_index.write_text("".join(json.dumps(item, sort_keys=True)+"\n" for item in index))
        print(f"M13 corpus {position}/{len(planned['incidents'])} {case['incident_id']} valid={valid} spans={len(telemetry['traces'])}", flush=True)
    (RUN_DIR / "truth.jsonl").write_text("".join(json.dumps(item, sort_keys=True)+"\n" for item in truth))
    (RUN_DIR / "telemetry-index.jsonl").write_text("".join(json.dumps(item, sort_keys=True)+"\n" for item in index))
    return {"valid_incidents": len(truth), "clusters": planned["clusters"], "replacements": replacements, "truth_sha256": sha256_file(RUN_DIR / "truth.jsonl"), "index_sha256": sha256_file(RUN_DIR / "telemetry-index.jsonl")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("ready", "healthy", "canary", "corpus"))
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--baseline", type=int, default=600)
    parser.add_argument("--duration", type=int, default=15)
    args = parser.parse_args()
    if args.command == "ready": result = ready()
    elif args.command == "healthy": result = healthy(args.warmup, args.baseline)
    elif args.command == "canary": result = canary(args.duration)
    else: result = corpus(args.duration)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
