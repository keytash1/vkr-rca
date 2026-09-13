#!/usr/bin/env python3
"""Locked Astronomy Shop deployment, collection and sealing for M14."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
SOURCE = ROOT / "external-data/m14/opentelemetry-demo"
RUN_DIR = ROOT / "external-data/m14/runs/locked-v1"
MODEL_DIR = ROOT / "ml/models/m14"
CONFIG = json.loads((ROOT / "deploy/m14/config.json").read_text())
SERVICES = tuple(CONFIG["candidate_services"])
TARGETS = tuple(CONFIG["target_services"])
FAULTS = tuple(CONFIG["fault_families"])
RPS = int(CONFIG["workload"]["requests_per_second"])
SEED = int(CONFIG["incident"]["randomization_seed"])
FRONTEND_URL = os.getenv("M14_FRONTEND_URL", "http://127.0.0.1:15014")
PROMETHEUS_URL = os.getenv("M14_PROMETHEUS_URL", "http://127.0.0.1:19092")
JAEGER_URL = os.getenv("M14_JAEGER_URL", "http://127.0.0.1:16689")
COMPOSE = [
    "docker", "compose", "--project-name", "vkr-rca-m14",
    "-f", str(SOURCE / "compose.yaml"), "-f", str(ROOT / "deploy/m14/compose.yml"),
]

sys.path.insert(0, str(ROOT / "ml"))
from rca_ml.dataset import sha256_file  # noqa: E402
from rca_ml.m12_adapter import CANONICAL_UNITS, robust_baseline  # noqa: E402
from rca_ml.m12_evaluate import MODEL_ARTIFACTS  # noqa: E402
from rca_ml.m13_features import fit_healthy_baseline  # noqa: E402
from rca_ml.m13_trace import canonicalize_jaeger  # noqa: E402

QUERIES = {
    "cpu": "m14_container_cpu_cores",
    "memory": "m14_container_memory_working_set_bytes",
    "network": "rate(m14_container_network_receive_bytes_total[5s]) + rate(m14_container_network_transmit_bytes_total[5s])",
    "traffic_rate": "rate(m14_container_network_receive_bytes_total[5s])",
}

DEPLOYMENT_DEVIATIONS = [
    "QUOTE_COMPOSER_ADVISORY_BUILD_SHIM",
    "AD_DOWNLOAD_TRANSPORT_BUILD_SHIM",
    "IMAGE_PROVIDER_OFFICIAL_3_0_0_PINNED_IMAGE",
    "UNUSED_SUPPORT_SERVICES_INERT",
]


def command(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "M14_ROOT": str(ROOT), "DEMO_VERSION": "m14-locked"}
    return subprocess.run([*COMPOSE, *args], cwd=SOURCE, env=env, check=check, text=True, capture_output=capture)


def verify_source() -> str:
    if not (SOURCE / ".git").is_dir():
        raise RuntimeError("run scripts/m14/setup.sh before M14")
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SOURCE, check=True, text=True, capture_output=True).stdout.strip()
    if actual != CONFIG["upstream"]["commit"]:
        raise RuntimeError(f"Astronomy Shop commit drift: {actual}")
    for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        if subprocess.run(["git", *args], cwd=SOURCE).returncode:
            raise RuntimeError("Astronomy Shop checkout has local changes")
    return actual


def up() -> dict:
    commit = verify_source()
    command("--profile", "tools", "build", "fault-tool", "metrics-exporter")
    command("up", "--build", "-d")
    return {"upstream_commit": commit, "compose_project": "vkr-rca-m14"}


def down() -> dict:
    command("down", "--remove-orphans")
    return {"stopped": True}


def prom(query: str, start: float | None = None, end: float | None = None) -> list[dict]:
    endpoint = "/api/v1/query_range" if start is not None else "/api/v1/query"
    params = {"query": query}
    if start is not None:
        params.update({"start": str(start), "end": str(end), "step": "1s"})
    with urllib.request.urlopen(PROMETHEUS_URL + endpoint + "?" + urllib.parse.urlencode(params), timeout=30) as response:
        payload = json.load(response)
    if payload["status"] != "success":
        raise RuntimeError(payload)
    return payload["data"]["result"]


def ready() -> dict:
    started, deadline, last = time.time(), time.time() + 600, ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(FRONTEND_URL + "/", timeout=5) as response:
                if response.status == 200:
                    break
        except Exception as error:
            last = str(error)
        time.sleep(3)
    else:
        raise RuntimeError(f"Astronomy Shop readiness timeout: {last}")
    while time.time() < deadline:
        try:
            result = prom('up{job="m14-container-metrics"}')
            if result and float(result[0]["value"][1]) == 1:
                break
        except Exception as error:
            last = str(error)
        time.sleep(2)
    else:
        raise RuntimeError(f"M14 metric readiness timeout: {last}")
    running = set(command("ps", "--services", "--status", "running", capture=True).stdout.split())
    missing = sorted(set(SERVICES) - running)
    if missing:
        raise RuntimeError(f"M14 application services not running: {missing}")
    images = {}
    for service in SERVICES:
        cid = container_id(service)
        images[service] = subprocess.run(
            ["docker", "inspect", "-f", "{{.Image}}", cid], check=True, text=True, capture_output=True,
        ).stdout.strip()
    result = {
        "upstream_commit": verify_source(), "ready_seconds": time.time() - started,
        "candidate_services": list(SERVICES), "application_image_ids": images,
        "host": {"platform": platform.platform(), "python": platform.python_version()},
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "readiness.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def collect_metrics(start: float, end: float) -> list[dict]:
    output = []
    for family, query in QUERIES.items():
        for series in prom(query, start, end):
            service = series["metric"].get("service")
            if service not in SERVICES:
                continue
            for timestamp, value in series.get("values", []):
                number = float(value)
                if np.isfinite(number):
                    output.append({"timestamp": int(float(timestamp)), "service": service, "family": family, "value": number, "unit": CANONICAL_UNITS[family]})
    output.sort(key=lambda item: (item["timestamp"], item["service"], item["family"]))
    return output


def collect_traces(start: float, end: float) -> tuple[list[dict], bool]:
    traces: dict[str, dict] = {}
    left = start
    try:
        while left < end:
            right = min(end, left + 15)
            params = urllib.parse.urlencode({"service": "frontend", "start": int(left * 1_000_000), "end": int(right * 1_000_000), "limit": 2000})
            with urllib.request.urlopen(JAEGER_URL + "/api/traces?" + params, timeout=30) as response:
                payload = json.load(response)
            for trace in payload.get("data", []):
                traces[str(trace["traceID"])] = trace
            left = right
    except Exception:
        return [], False
    return canonicalize_jaeger({"data": list(traces.values())}), True


def workload_thread(duration: float, seed: int):
    result: dict = {}
    def target() -> None:
        proc = subprocess.run([
            sys.executable, str(ROOT / "scripts/m14/workload.py"), "--base", FRONTEND_URL,
            "--duration", str(duration), "--rps", str(RPS), "--seed", str(seed),
        ], cwd=ROOT, text=True, capture_output=True)
        result.update({"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()})
    thread = threading.Thread(target=target, daemon=True); thread.start(); return thread, result


def validate_workload(result: dict, *, phase: str, allow_failures: bool = False) -> dict:
    if result.get("returncode") != 0 or not result.get("stdout"):
        raise RuntimeError(f"M14 {phase} workload failed: {result}")
    payload = json.loads(result["stdout"])
    failures = sum(count for status, count in payload["statuses"].items() if not 200 <= int(status) < 300)
    if failures and not allow_failures:
        raise RuntimeError(f"M14 {phase} has {failures}/{payload['attempts']} failures: {payload['statuses']}")
    if payload["attempts"] <= 0 or payload["dispatch_rate"] < .99 * payload["requests_per_second"]:
        raise RuntimeError(f"M14 {phase} violated dispatch contract: {payload}")
    return payload


def healthy(warmup: int, baseline_seconds: int) -> dict:
    warm, warm_result = workload_thread(warmup, SEED); warm.join(); validate_workload(warm_result, phase="warm-up")
    start = time.time(); thread, workload = workload_thread(baseline_seconds, SEED + 1); thread.join(); validate_workload(workload, phase="healthy baseline"); end = time.time()
    time.sleep(4)
    metrics = collect_metrics(start, end); traces, collected = collect_traces(start, end)
    coverage = {(item["service"], item["family"]) for item in metrics}
    missing = [(service, family) for service in SERVICES for family in QUERIES if (service, family) not in coverage]
    if missing or not collected or not traces:
        raise RuntimeError(f"M14 healthy telemetry incomplete: metrics={missing}, traces={len(traces)}, collected={collected}")
    output = {
        "role": "M14_HEALTHY_ENGINEERING", "warmup_seconds": warmup, "baseline_seconds": baseline_seconds,
        "scrape_interval_seconds": 1, "segments": [{"start_unix": start, "end_unix": end, "workload_regime": "mixed_steady", "requests_per_second": RPS}],
        "metrics": metrics, "traces": traces, "traces_collected": collected, "warmup_result": warm_result,
        "baseline_workload_result": workload, "protocol_deviations": list(DEPLOYMENT_DEVIATIONS),
    }
    path = RUN_DIR / "healthy"; path.mkdir(parents=True, exist_ok=True)
    (path / "baseline.json").write_text(json.dumps(output, separators=(",", ":")))
    fit_target_baselines(output)
    return {"metrics": len(metrics), "spans": len(traces), "seconds": end - start}


def fit_target_baselines(healthy_data: dict) -> None:
    target = fit_healthy_baseline(healthy_data, SERVICES)
    legacy = robust_baseline(healthy_data["metrics"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "healthy-baseline.json").write_text(json.dumps(target, indent=2, sort_keys=True) + "\n")
    (MODEL_DIR / "legacy-metric-baseline.json").write_text(json.dumps(legacy, indent=2, sort_keys=True) + "\n")


def container_id(service: str) -> str:
    ids = command("ps", "-q", service, capture=True).stdout.strip().splitlines()
    if len(ids) != 1:
        raise RuntimeError(f"expected one container for {service}, got {ids}")
    return ids[0]


def netem(service: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([
        "docker", "run", "--rm", "--network", f"container:{container_id(service)}", "--cap-add", "NET_ADMIN",
        "vkr-rca-m14/fault-tool:v1", *args,
    ], cwd=ROOT, text=True, capture_output=True, check=check)


def prepare_agent(service: str) -> None:
    architecture = subprocess.run(["docker", "info", "--format", "{{.Architecture}}"], check=True, text=True, capture_output=True).stdout.strip()
    goarch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(architecture)
    if goarch is None:
        raise RuntimeError(f"unsupported Docker architecture: {architecture}")
    binary = RUN_DIR / "m14-fault-agent"; binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["go", "build", "-trimpath", "-o", str(binary), str(ROOT / "scripts/m14/fault_agent.go")], check=True, env={**os.environ, "CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": goarch})
    subprocess.run(["docker", "cp", str(binary), f"{container_id(service)}:/tmp/m14-fault-agent"], check=True)


def inject(service: str, fault: str, duration: int) -> dict:
    if fault in {"cpu", "memory"}:
        proc = command("exec", "-T", "-d", service, "/tmp/m14-fault-agent", fault, str(duration), capture=True)
        criterion = f"target runs frozen {fault} agent"
    elif fault == "network_latency":
        proc = netem(service, "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", "200ms")
        criterion = "target netns reports 200ms delay"
    elif fault == "packet_loss":
        proc = netem(service, "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", "15%")
        criterion = "target netns reports 15% loss"
    elif fault == "service_unavailable":
        proc = command("pause", service, capture=True); criterion = "Docker reports target paused"
    else:
        raise ValueError(fault)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "criterion": criterion}


def mechanism_state(service: str, fault: str) -> str:
    if fault in {"network_latency", "packet_loss"}:
        return netem(service, "qdisc", "show", "dev", "eth0").stdout.strip()
    if fault == "service_unavailable":
        return subprocess.run(["docker", "inspect", "-f", "{{.State.Paused}}", container_id(service)], check=True, text=True, capture_output=True).stdout.strip()
    return subprocess.run(["docker", "top", container_id(service), "-eo", "args"], check=True, text=True, capture_output=True).stdout


def reset_fault(service: str, fault: str) -> None:
    if fault in {"network_latency", "packet_loss"}:
        netem(service, "qdisc", "del", "dev", "eth0", "root", check=False)
    elif fault == "service_unavailable":
        command("unpause", service, check=False, capture=True)


def valid_injection(service: str, fault: str, state: str, metrics: list[dict], healthy_data: dict) -> bool:
    if fault == "network_latency": return "delay 200ms" in state
    if fault == "packet_loss": return "loss 15%" in state
    if fault == "service_unavailable": return state == "true"
    if "m14-fault-agent" not in state: return False
    family = "cpu" if fault == "cpu" else "memory"
    observed = [item["value"] for item in metrics if item["service"] == service and item["family"] == family]
    normal = [item["value"] for item in healthy_data["metrics"] if item["service"] == service and item["family"] == family]
    threshold = .25 if fault == "cpu" else 16 * 1024 * 1024
    return bool(observed and normal and max(observed) > float(np.quantile(normal, .9)) + threshold)


def capture_case(case: dict, duration: int, seed: int) -> tuple[dict, dict]:
    service, fault = case["root_service"], case["fault_family"]
    # Compilation/copying is setup, not part of the locked incident window.
    if fault in {"cpu", "memory"}:
        prepare_agent(service)
    start = time.time(); thread, workload = workload_thread(duration, seed); injected = False
    try:
        injection = inject(service, fault, duration); injected = True; time.sleep(2); state = mechanism_state(service, fault)
        thread.join(); validate_workload(workload, phase=case["incident_id"], allow_failures=True)
    finally:
        if injected: reset_fault(service, fault)
        if thread.is_alive(): thread.join(timeout=10)
    end = time.time(); time.sleep(int(CONFIG["incident"]["cooldown_seconds"]))
    metrics = collect_metrics(start, end); traces, collected = collect_traces(start, end)
    telemetry = {
        "incident_id": case["incident_id"], "start_unix": start, "end_unix": end,
        "requests_per_second": RPS, "candidate_services": list(SERVICES), "metrics": metrics,
        "traces": traces, "traces_collected": collected, "workload_result": workload,
    }
    truth = {**case, "injection_evidence": {"returncode": injection["returncode"], "state": state}}
    return telemetry, truth


def canary(duration: int) -> dict:
    healthy_data = json.loads((RUN_DIR / "healthy/baseline.json").read_text()); results = []
    for index, fault in enumerate(FAULTS):
        case = {"incident_id": f"m14-canary-{fault}", "root_service": "ad", "fault_family": fault, "workload_regime": "mixed_steady", "intensity": CONFIG["fault_intensity"][fault]}
        telemetry, truth = capture_case(case, duration, SEED + 100 + index)
        valid = valid_injection("ad", fault, truth["injection_evidence"]["state"], telemetry["metrics"], healthy_data)
        results.append({"fault_family": fault, "valid": valid, "evidence": truth["injection_evidence"], "spans": len(telemetry["traces"]), "rankings_generated": False})
    output = {"role": "M14_CANARY", "rankings_generated": False, "results": results}
    path = RUN_DIR / "canary"; path.mkdir(parents=True, exist_ok=True); (path / "validity.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    if not all(item["valid"] for item in results): raise RuntimeError("M14 canary gate failed")
    return output


def plan() -> dict:
    cases = [{"root_service": service, "fault_family": fault, "workload_regime": "mixed_steady", "intensity": CONFIG["fault_intensity"][fault], "repetition": repetition} for service in TARGETS for fault in FAULTS for repetition in (1, 2)]
    random.Random(SEED).shuffle(cases)
    for index, case in enumerate(cases, 1):
        digest = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:8]; case["incident_id"] = f"m14-{index:03d}-{digest}"
    return {"version": "m14-locked-plan-v1", "seed": SEED, "incidents": cases, "clusters": 25, "repetitions_per_cluster": 2}


def write_plan() -> dict:
    value = plan(); MODEL_DIR.mkdir(parents=True, exist_ok=True); (MODEL_DIR / "incident-plan.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n"); return value


def corpus(duration: int) -> dict:
    healthy_data = json.loads((RUN_DIR / "healthy/baseline.json").read_text())
    canary_data = json.loads((RUN_DIR / "canary/validity.json").read_text())
    if canary_data["rankings_generated"] or not all(item["valid"] for item in canary_data["results"]): raise RuntimeError("M14 canary gate not satisfied")
    planned = json.loads((MODEL_DIR / "incident-plan.json").read_text())
    if planned != plan(): raise RuntimeError("M14 incident plan drift")
    telemetry_dir = RUN_DIR / "locked/telemetry"; telemetry_dir.mkdir(parents=True, exist_ok=True)
    truth_progress = RUN_DIR / "locked/truth.progress.jsonl"; index_progress = RUN_DIR / "locked/telemetry-index.progress.jsonl"
    truth = [json.loads(line) for line in truth_progress.read_text().splitlines() if line] if truth_progress.exists() else []
    index = [json.loads(line) for line in index_progress.read_text().splitlines() if line] if index_progress.exists() else []
    completed = {item["incident_id"] for item in truth}
    if completed != {item["incident_id"] for item in index} or not completed <= {item["incident_id"] for item in planned["incidents"]}: raise RuntimeError("M14 resume checkpoint mismatch")
    replacements = sum(int(item.get("collection_attempt", 1)) - 1 for item in truth)
    for position, case in enumerate(planned["incidents"], 1):
        if case["incident_id"] in completed:
            print(f"M14 corpus {position}/50 {case['incident_id']} resumed", flush=True); continue
        for attempt in range(1, int(CONFIG["incident"]["maximum_collection_attempts"]) + 1):
            telemetry, truth_item = capture_case(case, duration, SEED + position * 10 + attempt)
            valid = valid_injection(case["root_service"], case["fault_family"], truth_item["injection_evidence"]["state"], telemetry["metrics"], healthy_data)
            truth_item["valid_injection"] = valid
            if valid: break
            replacements += 1
        if not valid: raise RuntimeError(f"M14 mechanical injection failed twice: {case['incident_id']}")
        path = telemetry_dir / f"{case['incident_id']}.json"; path.write_text(json.dumps(telemetry, separators=(",", ":")))
        truth_item["collection_attempt"] = attempt; truth.append(truth_item)
        index.append({"incident_id": case["incident_id"], "telemetry_path": str(path.relative_to(RUN_DIR)), "sha256": sha256_file(path)})
        truth_progress.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in truth)); index_progress.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in index))
        print(f"M14 corpus {position}/50 {case['incident_id']} valid={valid} spans={len(telemetry['traces'])}", flush=True)
    truth_path = RUN_DIR / "locked/truth.sealed.jsonl"; index_path = RUN_DIR / "locked/telemetry-index.jsonl"
    truth_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in truth)); index_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in index))
    return {"valid_incidents": len(truth), "clusters": 25, "replacements": replacements, "truth_sha256": sha256_file(truth_path), "index_sha256": sha256_file(index_path)}


def freeze() -> dict:
    planned = json.loads((MODEL_DIR / "incident-plan.json").read_text()); index_path = RUN_DIR / "locked/telemetry-index.jsonl"; truth_path = RUN_DIR / "locked/truth.sealed.jsonl"
    index = [json.loads(line) for line in index_path.read_text().splitlines() if line]; truth = [json.loads(line) for line in truth_path.read_text().splitlines() if line]
    if len(index) != 50 or len(truth) != 50 or {item["incident_id"] for item in index} != {item["incident_id"] for item in truth} or not all(item["valid_injection"] for item in truth): raise RuntimeError("M14 locked denominator is not exactly 50 valid incidents")
    if {item["incident_id"] for item in truth} != {item["incident_id"] for item in planned["incidents"]}: raise RuntimeError("M14 data differs from pre-registered plan")
    for item in index:
        if sha256_file(RUN_DIR / item["telemetry_path"]) != item["sha256"]: raise RuntimeError(f"telemetry seal mismatch: {item['incident_id']}")
    healthy_path = RUN_DIR / "healthy/baseline.json"; healthy_data = json.loads(healthy_path.read_text())
    if healthy_data["warmup_seconds"] != CONFIG["healthy"]["warmup_seconds"] or healthy_data["baseline_seconds"] != CONFIG["healthy"]["baseline_seconds"]: raise RuntimeError("healthy duration differs from pre-registration")
    expected_baselines = {
        "healthy-baseline.json": fit_healthy_baseline(healthy_data, SERVICES),
        "legacy-metric-baseline.json": robust_baseline(healthy_data["metrics"]),
    }
    for name, expected in expected_baselines.items():
        if json.loads((MODEL_DIR / name).read_text()) != expected:
            raise RuntimeError(f"M14 healthy-only baseline drift: {name}")
    m13 = json.loads((ROOT / "ml/models/m13/freeze-manifest.json").read_text())
    frozen_inputs = {
        "m13_freeze_sha256": sha256_file(ROOT / "ml/models/m13/freeze-manifest.json"),
        "m13_models": m13["models"], "m13_feature_schema": m13["feature_schema"],
        "m13_hyperparameters": m13["hyperparameters"], "m13_selected_architecture": m13["selected_architecture"],
        "m13_runtime_sha256": sha256_file(ROOT / "ml/rca_ml/m13_runtime.py"),
        "m13_features_sha256": sha256_file(ROOT / "ml/rca_ml/m13_features.py"),
        "m13_trace_sha256": sha256_file(ROOT / "ml/rca_ml/m13_trace.py"),
        "m11_model_sha256": {path.name: sha256_file(path) for path in sorted((ROOT / "ml/models/m11").glob("candidate-recovery-k5-seed-*.json"))},
    }
    input_paths = set((ROOT / "ml/rca_ml").glob("*.py"))
    input_paths.update(ROOT / name for name in MODEL_ARTIFACTS)
    input_paths.update(ROOT / "ml/models/m13" / name for name in m13["models"])
    input_paths.update(ROOT / name for name in (
        "ml/models/m13/freeze-manifest.json", "ml/models/m10c-v2/feature-schema.json",
        "ml/models/m12/ood-stats.json", "scripts/m14/run.py", "scripts/m14/workload.py",
        "scripts/m14/fault_agent.go", "deploy/m14/compose.yml",
    ))
    frozen_inputs["files"] = {str(path.relative_to(ROOT)): sha256_file(path) for path in sorted(input_paths)}
    (MODEL_DIR / "frozen-inputs.json").write_text(json.dumps(frozen_inputs, indent=2, sort_keys=True) + "\n")
    result = {
        "version": "m14-final-freeze-v1", "status": "SEALED_UNSCORED", "upstream_commit": verify_source(),
        "config_sha256": sha256_file(ROOT / "deploy/m14/config.json"), "protocol_sha256": sha256_file(ROOT / "docs/m14-protocol.md"),
        "incident_plan_sha256": sha256_file(MODEL_DIR / "incident-plan.json"), "healthy_raw_sha256": sha256_file(healthy_path),
        "healthy_baseline_sha256": sha256_file(MODEL_DIR / "healthy-baseline.json"), "legacy_baseline_sha256": sha256_file(MODEL_DIR / "legacy-metric-baseline.json"),
        "locked_truth_sha256": sha256_file(truth_path), "telemetry_index_sha256": sha256_file(index_path),
        "telemetry_sha256": {item["incident_id"]: item["sha256"] for item in index}, "frozen_inputs_sha256": sha256_file(MODEL_DIR / "frozen-inputs.json"),
        "rankings_generated": False, "truth_opened_for_evaluation": False,
    }
    (MODEL_DIR / "freeze-manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("up", "down", "ready", "plan", "healthy", "canary", "corpus", "freeze"))
    parser.add_argument("--warmup", type=int, default=int(CONFIG["healthy"]["warmup_seconds"])); parser.add_argument("--baseline", type=int, default=int(CONFIG["healthy"]["baseline_seconds"])); parser.add_argument("--duration", type=int, default=int(CONFIG["incident"]["duration_seconds"]))
    args = parser.parse_args()
    if args.command == "up": result = up()
    elif args.command == "down": result = down()
    elif args.command == "ready": result = ready()
    elif args.command == "plan": result = write_plan()
    elif args.command == "healthy": result = healthy(args.warmup, args.baseline)
    elif args.command == "canary": result = canary(args.duration)
    elif args.command == "corpus": result = corpus(args.duration)
    else: result = freeze()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()
