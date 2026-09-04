"""Live, external incident generator for the M7 research dataset."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .dataset import enrich_labels, read_jsonl, sha256_file, write_jsonl
from .schema import SOURCE_FEATURE_SCHEMA_VERSION


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = 20260904
    incidents_per_pair: int = 100
    healthy_controls: int = 60
    baseline_requests: int = 100
    requests_per_incident: int = 20
    concurrency: int = 20
    drain_seconds: float = 0.25
    collector_settle_seconds: float = 1.25
    poll_interval_seconds: float = 0.2
    poll_timeout_seconds: float = 20.0
    latency_min_ms: int = 1
    latency_max_ms: int = 700
    error_min_rate: float = 0.1
    error_max_rate: float = 1.0


class RCAClient:
    def __init__(
        self,
        gateway: str,
        orders: str | None = None,
        payment: str | None = None,
        rca: str | None = None,
        *,
        fault_urls: dict[str, str] | None = None,
        work_path: str = "/api/order",
    ) -> None:
        if rca is None:
            raise ValueError("RCA URL is required")
        self.gateway = gateway.rstrip("/")
        self.rca = rca.rstrip("/")
        self.work_path = "/" + work_path.strip("/")
        self.fault_urls = (
            {service: url.rstrip("/") for service, url in fault_urls.items()}
            if fault_urls is not None
            else {
                "gateway": gateway.rstrip("/"),
                "orders": (orders or "").rstrip("/"),
                "payment": (payment or "").rstrip("/"),
            }
        )
        if not self.fault_urls or any(not value for value in self.fault_urls.values()):
            raise ValueError("fault URLs are required")

    def get_json(self, url: str) -> dict:
        return self._json("GET", url)

    def post_json(self, url: str, payload: dict | None = None) -> dict:
        return self._json("POST", url, payload)

    def _json(self, method: str, url: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def reset_faults(self) -> None:
        for service in sorted(self.fault_urls):
            self.post_json(f"{self.fault_urls[service]}/debug/reset")

    def set_fault(self, service: str, *, latency_ms: int = 0, error_rate: float = 0.0) -> None:
        self.post_json(
            f"{self.fault_urls[service]}/debug/fault",
            {"latency_ms": latency_ms, "error_rate": error_rate},
        )

    def reset_current(self) -> None:
        self.post_json(f"{self.rca}/debug/anomaly/reset")

    def send_traffic(self, incident_id: str, count: int, concurrency: int) -> dict[str, int]:
        def request(index: int) -> int:
            call = urllib.request.Request(
                f"{self.gateway}{self.work_path}",
                headers={"X-Request-ID": f"{incident_id}-{index:03d}"},
            )
            try:
                with urllib.request.urlopen(call, timeout=10) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as error:
                error.read()
                return error.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            statuses = list(executor.map(request, range(count)))
        return {str(code): occurrences for code, occurrences in sorted(Counter(statuses).items())}


def prepare_incident(client: RCAClient, config: GenerationConfig) -> int:
    """Drain prior batches, reset, and prove an empty M5 current window."""
    client.reset_faults()
    time.sleep(config.drain_seconds)
    resets = 0
    for _ in range(10):
        client.reset_current()
        resets += 1
        time.sleep(config.poll_interval_seconds)
        anomaly = client.get_json(f"{client.rca}/api/anomalies")
        if all(int(operation.get("current_samples", 0)) == 0 for operation in anomaly.get("operations", [])):
            return resets
    raise RuntimeError("collector drain barrier did not reach an empty current window")


def wait_for_samples(
    client: RCAClient,
    services: list[str],
    count: int,
    config: GenerationConfig,
    top_up: Callable[[int], None] | None = None,
) -> int:
    last = None
    for cycle in range(3):
        deadline = time.monotonic() + config.poll_timeout_seconds
        while time.monotonic() < deadline:
            last = client.get_json(f"{client.rca}/api/anomalies")
            counts = {
                operation["service"]: int(operation.get("current_samples", 0))
                for operation in last.get("operations", [])
            }
            if all(counts.get(service, 0) >= count for service in services):
                return cycle
            time.sleep(config.poll_interval_seconds)
        if top_up is None or cycle == 2:
            break
        top_up(cycle + 1)
    raise RuntimeError(f"timed out waiting for current samples: services={services}, last={last}")


def collect_baseline(client: RCAClient, config: GenerationConfig) -> dict:
    client.reset_faults()
    time.sleep(config.drain_seconds)
    client.post_json(f"{client.rca}/debug/baseline/start")
    client.send_traffic("m7-baseline", config.baseline_requests, config.concurrency)
    deadline = time.monotonic() + config.poll_timeout_seconds
    while time.monotonic() < deadline:
        baseline = client.get_json(f"{client.rca}/api/baseline")
        operations = baseline.get("operations", [])
        observed_services = {value.get("service") for value in operations}
        if set(client.fault_urls) <= observed_services and all(
            int(value.get("samples", 0)) >= config.baseline_requests for value in operations
        ):
            frozen = client.post_json(f"{client.rca}/debug/baseline/freeze")
            if frozen.get("state") != "frozen":
                raise RuntimeError("baseline did not freeze")
            return frozen
        time.sleep(config.poll_interval_seconds)
    raise RuntimeError("timed out collecting M7 baseline")


def scenarios(config: GenerationConfig) -> list[dict]:
    randomizer = random.Random(config.seed)
    values: list[dict] = []
    for root in ("gateway", "orders", "payment"):
        for fault_type in ("latency", "error"):
            for pair_index in range(config.incidents_per_pair):
                if fault_type == "latency":
                    raw = math.exp(randomizer.uniform(math.log(config.latency_min_ms), math.log(config.latency_max_ms)))
                    fault_value: int | float = max(config.latency_min_ms, min(config.latency_max_ms, int(round(raw))))
                else:
                    fault_value = round(randomizer.uniform(config.error_min_rate, config.error_max_rate), 6)
                fingerprint_input = {
                    "root_service": root,
                    "fault_type": fault_type,
                    "fault_value": fault_value,
                    "generation_seed": config.seed,
                    "generation_index": pair_index,
                }
                fingerprint = hashlib.sha256(
                    json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                values.append(
                    {
                        "incident_type": "fault",
                        "root_service": root,
                        "fault_type": fault_type,
                        "fault_value": fault_value,
                        "pair_index": pair_index,
                        "scenario_fingerprint": fingerprint,
                    }
                )
    for control_index in range(config.healthy_controls):
        fingerprint = hashlib.sha256(f"healthy:{config.seed}:{control_index}".encode()).hexdigest()
        values.append(
            {
                "incident_type": "healthy",
                "root_service": None,
                "fault_type": "none",
                "fault_value": 0,
                "pair_index": control_index,
                "scenario_fingerprint": fingerprint,
            }
        )
    randomizer.shuffle(values)
    for index, value in enumerate(values):
        value["incident_id"] = f"m7-{index:05d}"
    return values


def generate(output_dir: Path, client: RCAClient, config: GenerationConfig) -> dict:
    features_path = output_dir / "features.jsonl"
    labels_path = output_dir / "labels.jsonl"
    all_scenarios = scenarios(config)
    if output_dir.exists():
        if (output_dir / "manifest.json").exists():
            raise FileExistsError(f"completed dataset already exists: {output_dir}")
        existing_features = read_jsonl(features_path)
        existing_labels = read_jsonl(labels_path)
        if len(existing_features) != len(existing_labels):
            raise ValueError("cannot resume: features and labels line counts differ")
        expected_ids = [scenario["incident_id"] for scenario in all_scenarios[: len(existing_features)]]
        if [record["incident_id"] for record in existing_features] != expected_ids or [
            record["incident_id"] for record in existing_labels
        ] != expected_ids:
            raise ValueError("cannot resume: existing incident sequence differs")
        baseline = client.get_json(f"{client.rca}/api/baseline")
        if baseline.get("state") != "frozen" or not all(
            int(operation.get("samples", 0)) >= config.baseline_requests
            for operation in baseline.get("operations", [])
        ):
            raise ValueError("cannot resume without the original frozen baseline")
        start_index = len(existing_features)
        file_mode = "a"
        started = existing_features[0].get("captured_at", _utc_now()) if existing_features else _utc_now()
        print(f"resuming at {start_index}/{len(all_scenarios)}", flush=True)
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        baseline = collect_baseline(client, config)
        start_index = 0
        file_mode = "w"
        started = _utc_now()
    with features_path.open(file_mode, encoding="utf-8") as feature_output, labels_path.open(
        file_mode, encoding="utf-8"
    ) as label_output:
        for number, scenario in enumerate(all_scenarios[start_index:], start_index + 1):
            incident_id = scenario["incident_id"]
            drain_resets = prepare_incident(client, config)
            if scenario["incident_type"] == "fault":
                if scenario["fault_type"] == "latency":
                    client.set_fault(scenario["root_service"], latency_ms=int(scenario["fault_value"]))
                else:
                    client.set_fault(scenario["root_service"], error_rate=float(scenario["fault_value"]))
            statuses = Counter(client.send_traffic(incident_id, config.requests_per_incident, config.concurrency))
            if scenario["fault_type"] in {"latency", "none"}:
                required = ["gateway", "orders", "payment"]
            else:
                required = {
                    "gateway": ["gateway"],
                    "orders": ["gateway", "orders"],
                    "payment": ["gateway", "orders", "payment"],
                }[scenario["root_service"]]
            def top_up(cycle: int) -> None:
                extra = client.send_traffic(f"{incident_id}-topup-{cycle}", 5, min(5, config.concurrency))
                statuses.update(extra)

            top_up_cycles = wait_for_samples(
                client,
                required,
                config.requests_per_incident,
                config,
                top_up=top_up,
            )
            if scenario["fault_type"] == "error":
                time.sleep(config.collector_settle_seconds)
            snapshot = client.get_json(f"{client.rca}/api/features")
            rankings = client.get_json(f"{client.rca}/api/rca")
            feature_record = {
                "incident_id": incident_id,
                "captured_at": _utc_now(),
                "feature_snapshot": snapshot,
                "m6_rankings": rankings,
            }
            feature_output.write(json.dumps(feature_record, sort_keys=True, separators=(",", ":")) + "\n")
            feature_output.flush()
            os.fsync(feature_output.fileno())
            label_record = {
                **scenario,
                "generation_seed": config.seed,
                "generation_metadata": {
                    "sequence_number": number,
                    "traffic_requests": config.requests_per_incident + top_up_cycles * 5,
                    "top_up_cycles": top_up_cycles,
                    "concurrency": config.concurrency,
                    "http_status_counts": dict(sorted(statuses.items())),
                    "drain_resets": drain_resets,
                },
            }
            label_output.write(json.dumps(label_record, sort_keys=True, separators=(",", ":")) + "\n")
            label_output.flush()
            os.fsync(label_output.fileno())
            if number % 10 == 0 or number == config.healthy_controls + 6 * config.incidents_per_pair:
                print(f"generated {number}/{config.healthy_controls + 6 * config.incidents_per_pair}", flush=True)
    client.reset_faults()
    feature_records = read_jsonl(features_path)
    enriched = enrich_labels(feature_records, read_jsonl(labels_path))
    write_jsonl(labels_path, enriched)
    manifest = {
        "dataset_schema_version": "m7-v1",
        "m6_feature_schema_version": SOURCE_FEATURE_SCHEMA_VERSION,
        "git_commit": _git_commit(),
        "generated_at": _utc_now(),
        "generation_started_at": started,
        "random_seed": config.seed,
        "number_of_fault_incidents": 6 * config.incidents_per_pair,
        "number_of_healthy_controls": config.healthy_controls,
        "baseline_configuration": {
            "requests": config.baseline_requests,
            "operations": baseline.get("operations", []),
        },
        "m5_thresholds": {"latency_z": 3.5, "error_z": 3.0},
        "window_sizes": {"current": config.requests_per_incident, "minimum_current": 10},
        "scenario_generation_configuration": asdict(config),
        "collector_drain_strategy": "wait after fault reset, reset current, then verify every anomaly current_samples value is zero",
        "services": ["gateway", "orders", "payment"],
        "fault_types": ["latency", "error"],
        "sha256": {"features.jsonl": sha256_file(features_path), "labels.jsonl": sha256_file(labels_path)},
        "python": {"version": platform.python_version(), "packages": _package_versions()},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _package_versions() -> dict[str, str]:
    import numpy
    import scipy
    import xgboost

    return {"numpy": numpy.__version__, "scipy": scipy.__version__, "xgboost": xgboost.__version__}


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--incidents-per-pair", type=int, default=100)
    parser.add_argument("--healthy-controls", type=int, default=60)
    parser.add_argument("--baseline-requests", type=int, default=100)
    parser.add_argument("--requests-per-incident", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--gateway-url", default="http://localhost:18080")
    parser.add_argument("--orders-url", default="http://localhost:8081")
    parser.add_argument("--payment-url", default="http://localhost:8082")
    parser.add_argument("--rca-url", default="http://localhost:18090")
    args = parser.parse_args()
    config = GenerationConfig(
        seed=args.seed,
        incidents_per_pair=args.incidents_per_pair,
        healthy_controls=args.healthy_controls,
        baseline_requests=args.baseline_requests,
        requests_per_incident=args.requests_per_incident,
        concurrency=args.concurrency,
    )
    client = RCAClient(args.gateway_url, args.orders_url, args.payment_url, args.rca_url)
    manifest = generate(args.output_dir, client, config)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
