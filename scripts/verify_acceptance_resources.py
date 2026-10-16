"""Compare acceptance telemetry with Docker counters under a bounded CPU probe.

Touches only one explicitly selected application container from our isolated
acceptance project. No classifier, labels or research thresholds are involved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import urlopen

DOCKER = "/opt/homebrew/bin/docker"
PROJECT = "rca-product-acceptance"


class DockerConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost", timeout=10)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.socket_path)


def docker_json(socket_path: str, path: str):
    connection = DockerConnection(socket_path)
    try:
        connection.request("GET", "/v1.44" + path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Docker request returned {response.status}")
        return json.load(response)
    finally:
        connection.close()


def query(expression: str):
    with urlopen("http://127.0.0.1:19990/api/v1/query?" + urlencode({"query": expression}), timeout=10) as response:
        result = json.load(response)
    if result.get("status") != "success" or len(result["data"]["result"]) != 1:
        raise RuntimeError(f"expected one metric: {expression}")
    return result["data"]["result"][0]["value"]


def run(socket_path: str, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("refusing to overwrite an acceptance record")
    filters = json.dumps({"label": ["com.docker.compose.project=" + PROJECT,
                                  "com.docker.compose.service=gateway"]})
    containers = docker_json(socket_path, "/containers/json?" + urlencode({"filters": filters}))
    if len(containers) != 1:
        raise RuntimeError("expected exactly our acceptance gateway")
    container = containers[0]
    if container["Labels"].get("io.vkr.telemetry") != "enabled":
        raise RuntimeError("target is not an instrumented acceptance container")
    identifier = container["Id"]
    path = f"/containers/{identifier}/stats?stream=false&one-shot=true"
    before = query('sum(rca_container_cpu_cores{service="gateway"})')
    # Docker exec is tied to the verified container ID; timeout bounds the CPU
    # probe even if this controlling process exits. No application code changes.
    probe = subprocess.Popen([DOCKER, "exec", identifier, "timeout", "15", "sh", "-c", "while :; do :; done"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        time.sleep(3)
        first = docker_json(socket_path, path)
        time.sleep(5)
        second = docker_json(socket_path, path)
        exported = query('avg_over_time(rca_container_cpu_cores{service="gateway"}[5s])')
        memory = query('rca_container_memory_working_set_bytes{service="gateway"}')
        network = query('sum(rate(rca_container_network_receive_bytes_total{service="gateway"}[20s]))')
    finally:
        probe.wait(timeout=20)
    # Independent Docker CLI formula using system CPU ticks (the exporter uses
    # read timestamps and consumed nanoseconds, not this computation).
    cpu_delta = second["cpu_stats"]["cpu_usage"]["total_usage"] - first["cpu_stats"]["cpu_usage"]["total_usage"]
    system_delta = second["cpu_stats"]["system_cpu_usage"] - first["cpu_stats"]["system_cpu_usage"]
    reference = cpu_delta / system_delta * second["cpu_stats"]["online_cpus"]
    actual = float(exported[1])
    usage = second["memory_stats"]["usage"]
    cache = second["memory_stats"]["stats"].get("inactive_file", second["memory_stats"]["stats"].get("total_inactive_file", 0))
    reference_memory = max(0, usage - cache)
    checks = {
        "probe_observed_in_raw_counters": reference > 0.2,
        "cpu_matches_independent_formula": abs(actual - reference) <= max(0.1, reference * 0.25),
        "cpu_responds_to_current_load": actual > float(before[1]) + 0.15,
        "memory_matches_working_set": abs(float(memory[1]) - reference_memory) <= max(1_048_576, reference_memory * 0.05),
        "network_receive_rate_observed": float(network[1]) > 0,
    }
    record = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "project": PROJECT, "container_id": identifier,
              "raw_before": first, "raw_after": second,
              "cpu_before": before, "cpu_exported_during_probe": exported,
              "cpu_reference_cores": reference, "memory_exported": memory,
              "memory_reference_bytes": reference_memory, "network_receive_rate": network,
              "probe_exit_code": probe.returncode, "checks": checks,
              "purpose": "ENGINEERING_TELEMETRY_VALIDATION_NOT_MODEL_ACCURACY"}
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not all(checks.values()):
        raise RuntimeError(f"resource verification failed: {checks}")
    print(json.dumps({"status": "passed", "checks": checks, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-socket", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.docker_socket, args.output)
