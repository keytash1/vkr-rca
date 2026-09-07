#!/usr/bin/env python3
"""Reproducible M12 lifecycle: readiness, healthy data, canaries and locked runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from rca_ml.dataset import sha256_file  # noqa: E402
from rca_ml.m12_adapter import CANONICAL_UNITS, robust_baseline  # noqa: E402
from rca_ml.m12_evaluate import evaluate  # noqa: E402

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/m12/compose.yml")]
SERVICES = ["frontend", "profile", "search", "geo", "rate", "recommendation", "user", "reservation"]
TARGETS = ["frontend", "search", "geo", "rate", "recommendation"]
FAULTS = ["cpu", "memory", "network_latency", "packet_loss", "service_unavailable"]
EDGES = [
    {"source": "frontend", "target": "search"}, {"source": "frontend", "target": "profile"},
    {"source": "frontend", "target": "recommendation"}, {"source": "frontend", "target": "user"},
    {"source": "frontend", "target": "reservation"}, {"source": "search", "target": "geo"},
    {"source": "search", "target": "rate"}, {"source": "reservation", "target": "rate"},
]
RUN_DIR = ROOT / "external-data/m12/runs/locked-v1"


def command(*args: str, check: bool = True, capture: bool = False):
    return subprocess.run([*COMPOSE, *args], cwd=ROOT, check=check, text=True, capture_output=capture)


def ready() -> dict:
    started = time.time()
    deadline = started + 300
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:15000/", timeout=3) as response:
                if response.status == 200:
                    break
        except Exception as error:  # readiness evidence, not inference
            last = str(error)
        time.sleep(2)
    else:
        raise RuntimeError(f"frontend readiness timeout: {last}")
    prom_deadline = time.time() + 120
    while time.time() < prom_deadline:
        try:
            data = prom("up{job=\"m12-container-metrics\"}")
            if data and float(data[0]["value"][1]) == 1:
                result = {"application_probe_seconds": time.time() - started, "telemetry_probe_seconds": time.time() - started}
                path = RUN_DIR / "healthy"; path.mkdir(parents=True, exist_ok=True)
                (path / "readiness.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
                return result
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("Prometheus/cAdvisor readiness timeout")


def prom(query: str, start: float | None = None, end: float | None = None) -> list[dict]:
    endpoint = "/api/v1/query_range" if start is not None else "/api/v1/query"
    params = {"query": query}
    if start is not None:
        params.update({"start": str(start), "end": str(end), "step": "1s"})
    with urllib.request.urlopen("http://127.0.0.1:19090" + endpoint + "?" + urllib.parse.urlencode(params), timeout=20) as response:
        payload = json.load(response)
    if payload["status"] != "success":
        raise RuntimeError(payload)
    return payload["data"]["result"]


QUERIES = {
    "cpu": 'm12_container_cpu_cores',
    "memory": 'm12_container_memory_working_set_bytes',
    "network": 'rate(m12_container_network_receive_bytes_total[5s]) + rate(m12_container_network_transmit_bytes_total[5s])',
    "traffic_rate": 'rate(m12_container_network_receive_bytes_total[5s])',
}


def collect(start: float, end: float) -> list[dict]:
    output = []
    for family, query in QUERIES.items():
        for series in prom(query, start, end):
            labels = series["metric"]
            service = labels.get("service")
            if service not in SERVICES:
                continue
            for timestamp, value in series.get("values", []):
                output.append({"timestamp": int(float(timestamp)), "service": service, "family": family, "value": float(value), "unit": CANONICAL_UNITS[family]})
    output.sort(key=lambda item: (item["timestamp"], item["service"], item["family"]))
    return output


def workload_thread(duration: float):
    result = {}
    def target():
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/m12/workload.py"), "--duration", str(duration)], cwd=ROOT, text=True, capture_output=True)
        result.update({"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()})
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result


def healthy(warmup: int, baseline_duration: int) -> dict:
    path = RUN_DIR / "healthy"
    path.mkdir(parents=True, exist_ok=True)
    warm_thread, warm_result = workload_thread(warmup)
    warm_thread.join()
    start = time.time()
    thread, load = workload_thread(baseline_duration)
    thread.join()
    end = time.time()
    time.sleep(3)
    records = collect(start, end)
    baseline = robust_baseline(records)
    coverage = {service: sorted(baseline.get(service, {})) for service in SERVICES}
    if sum(bool(value) for value in coverage.values()) < 5:
        raise RuntimeError(f"compatibility gate failed: service metric coverage {coverage}")
    manifest = {
        "role": "M12_HEALTHY_ENGINEERING", "warmup_seconds": warmup,
        "baseline_seconds": baseline_duration, "scrape_interval_seconds": 1,
        "workload": json.loads((ROOT / "deploy/m12/workload.json").read_text()),
        "services": baseline, "coverage": coverage, "samples": len(records),
        "warmup_result": warm_result, "baseline_workload_result": load,
        "protocol_deviations": (["warm-up reduced from 300 seconds"] if warmup < 300 else [])
            + (["healthy baseline reduced from 900 seconds"] if baseline_duration < 900 else []),
    }
    if warm_result.get("returncode") != 0 or load.get("returncode") != 0:
        raise RuntimeError("healthy workload process failed")
    if min(value["samples"] for service in baseline.values() for value in service.values()) < 30:
        raise RuntimeError("healthy baseline has fewer than 30 real samples per service/family")
    (path / "baseline.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def inject(service: str, fault: str, duration: int) -> dict:
    if service not in TARGETS or fault not in FAULTS:
        raise ValueError("unregistered target/fault")
    if fault == "cpu":
        proc = command("exec", "-T", "-d", service, "stress-ng", "--cpu", "1", "--cpu-load", "90", "--timeout", f"{duration}s", capture=True)
        criterion = "injector exited 0 and target CPU exceeds healthy p90 in telemetry"
    elif fault == "memory":
        proc = command("exec", "-T", "-d", service, "stress-ng", "--vm", "1", "--vm-bytes", "128M", "--vm-keep", "--timeout", f"{duration}s", capture=True)
        criterion = "injector exited 0 and target memory exceeds healthy median by 64 MiB"
    elif fault == "network_latency":
        proc = command("exec", "-T", service, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", "250ms", capture=True)
        criterion = "target qdisc reports netem delay 250ms"
    elif fault == "packet_loss":
        proc = command("exec", "-T", service, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", "20%", capture=True)
        criterion = "target qdisc reports netem loss 20%"
    else:
        proc = command("pause", service, capture=True)
        criterion = "Docker reports target container paused"
    return {"returncode": proc.returncode, "criterion": criterion, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def reset_fault(service: str, fault: str) -> None:
    if fault in {"network_latency", "packet_loss"}:
        command("exec", "-T", service, "tc", "qdisc", "del", "dev", "eth0", "root", check=False, capture=True)
    elif fault == "service_unavailable":
        command("unpause", service, check=False, capture=True)
    elif fault in {"cpu", "memory"}:
        command("exec", "-T", service, "pkill", "-f", "stress-ng", check=False, capture=True)


def mechanism_state(service: str, fault: str) -> str:
    if fault in {"network_latency", "packet_loss"}:
        return command("exec", "-T", service, "tc", "qdisc", "show", "dev", "eth0", capture=True).stdout.strip()
    if fault == "service_unavailable":
        ids = command("ps", "-q", service, capture=True).stdout.strip().splitlines()
        return subprocess.run(["docker", "inspect", "-f", "{{.State.Paused}}", ids[0]], text=True, capture_output=True, check=True).stdout.strip()
    return command("exec", "-T", service, "pgrep", "-a", "stress-ng", check=False, capture=True).stdout.strip()


def valid_injection(service: str, fault: str, state: str, metrics: list[dict], baseline: dict) -> bool:
    values = [item["value"] for item in metrics if item["service"] == service and item["family"] == ("cpu" if fault == "cpu" else "memory")]
    if fault == "cpu":
        normal = baseline["services"][service]["cpu"]
        return bool(values) and max(values) > normal["median"] + max(3 * normal["iqr"], .15)
    if fault == "memory":
        normal = baseline["services"][service]["memory"]
        return bool(values) and max(values) > normal["median"] + 64 * 1024 * 1024
    if fault == "network_latency": return "delay 250ms" in state
    if fault == "packet_loss": return "loss 20%" in state
    return state == "true"


def canary(duration: int) -> dict:
    baseline = json.loads((RUN_DIR / "healthy/baseline.json").read_text())
    results = []
    for fault in FAULTS:
        service = "search"
        start = time.time()
        thread, workload = workload_thread(duration)
        injection = inject(service, fault, duration)
        time.sleep(2)
        state = mechanism_state(service, fault)
        thread.join()
        reset_fault(service, fault)
        end = time.time()
        time.sleep(3)
        records = collect(start, end)
        results.append({"fault_family": fault, "target": service, "injection": injection, "mechanism_state": state, "valid": valid_injection(service, fault, state, records, baseline), "workload": workload})
    output = {"role": "M12_CANARY", "rankings_generated": False, "results": results}
    path = RUN_DIR / "canary"
    path.mkdir(parents=True, exist_ok=True)
    (path / "validity.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    if not all(item["valid"] for item in results):
        raise RuntimeError("one or more fault canaries failed independent validity")
    return output


def incident_plan() -> dict:
    matrix = [{"root_service": target, "fault_family": fault, "repetition": rep} for target in TARGETS for fault in FAULTS for rep in (1, 2)]
    random.Random(20260906).shuffle(matrix)
    for index, item in enumerate(matrix, 1):
        item["incident_id"] = f"m12-{index:03d}-{hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:8]}"
        item["duration_seconds"] = 12
    return {"version": "m12-locked-plan-v1", "seed": 20260906, "incidents": matrix, "targets": TARGETS, "fault_families": FAULTS, "clusters": 25, "repetitions_per_cluster": 2}


def run_locked(duration: int) -> dict:
    plan_path = ROOT / "ml/models/m12/incident-plan.json"
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else incident_plan()
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    baseline = json.loads((RUN_DIR / "healthy/baseline.json").read_text())
    locked = RUN_DIR / "locked"
    locked.mkdir(parents=True, exist_ok=True)
    truth, index = [], []
    for position, case in enumerate(plan["incidents"], 1):
        service, fault = case["root_service"], case["fault_family"]
        start = time.time()
        thread, workload = workload_thread(duration)
        injection = inject(service, fault, duration)
        time.sleep(2)
        state = mechanism_state(service, fault)
        thread.join()
        reset_fault(service, fault)
        end = time.time()
        time.sleep(3)
        records = collect(start, end)
        valid = valid_injection(service, fault, state, records, baseline)
        telemetry = {"incident_id": case["incident_id"], "start_unix": start, "end_unix": end, "candidate_services": SERVICES, "edges": EDGES, "metrics": records, "workload_result": workload}
        telemetry_path = locked / f"{case['incident_id']}.json"
        telemetry_path.write_text(json.dumps(telemetry, sort_keys=True, separators=(",", ":")))
        truth.append({**case, "valid_injection": valid, "injection_evidence": {"command_returncode": injection["returncode"], "mechanism_state": state}})
        index.append({"incident_id": case["incident_id"], "telemetry_path": str(telemetry_path.relative_to(RUN_DIR)), "telemetry_sha256": sha256_file(telemetry_path)})
        print(f"M12 locked {position}/{len(plan['incidents'])} {case['incident_id']} valid={valid}", flush=True)
        if not valid:
            raise RuntimeError(f"invalid injection {case['incident_id']}; locked evaluation remains sealed")
        time.sleep(2)
    truth_path = locked / "truth.sealed.jsonl"
    truth_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in truth))
    (locked / "telemetry-index.jsonl").write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in index))
    return {"valid_incidents": len(index), "truth_sha256": sha256_file(truth_path), "telemetry_index_sha256": sha256_file(locked / "telemetry-index.jsonl")}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ready")
    healthy_parser = sub.add_parser("healthy"); healthy_parser.add_argument("--warmup", type=int, default=60); healthy_parser.add_argument("--baseline", type=int, default=180)
    canary_parser = sub.add_parser("canary"); canary_parser.add_argument("--duration", type=int, default=12)
    locked_parser = sub.add_parser("run-locked"); locked_parser.add_argument("--duration", type=int, default=12)
    sub.add_parser("plan")
    sub.add_parser("evaluate")
    args = parser.parse_args()
    if args.command == "ready": result = ready()
    elif args.command == "healthy": result = healthy(args.warmup, args.baseline)
    elif args.command == "canary": result = canary(args.duration)
    elif args.command == "run-locked": result = run_locked(args.duration)
    elif args.command == "plan": result = incident_plan(); (ROOT / "ml/models/m12/incident-plan.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else: result = evaluate(ROOT, RUN_DIR)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
