"""Independent bounded watchdog for our named non-production fault controls.

No arbitrary URL, command, container or filesystem path is accepted. It outlives
the collector's process group and resets only the exact applied teaching fault.
"""

import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"gateway": 18680, "orders": 18681, "payment": 18682}
PETCLINIC = {"api-gateway", "customers-service", "vets-service", "visits-service"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", choices=["local-three", "petclinic"], required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--kind", choices=["latency", "error", "pause"], required=True)
    parser.add_argument("--cancel-file", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    args = parser.parse_args()
    cancellation = args.cancel_file.resolve()
    if (
        not cancellation.is_relative_to((ROOT / ".rca-private/watchdogs").resolve())
        or not 0 < args.deadline - time.time() <= 65
    ):
        parser.error("invalid bounded watchdog scope")
    if args.system == "local-three" and (
        args.service not in PORTS or args.kind == "pause"
    ):
        parser.error("invalid Go teaching control")
    if args.system == "petclinic" and (
        args.service not in PETCLINIC or args.kind != "pause"
    ):
        parser.error("invalid Petclinic teaching control")
    while time.time() < args.deadline:
        if cancellation.exists():
            return
        time.sleep(0.25)
    if cancellation.exists():
        return
    if args.system == "local-three":
        endpoint = f"http://127.0.0.1:{PORTS[args.service]}/debug/fault"
        with urlopen(endpoint, timeout=5) as response:
            state = json.load(response)
        expected = {
            "latency_ms": 250 if args.kind == "latency" else 0,
            "error_rate": 1 if args.kind == "error" else 0,
        }
        if state == expected:
            with urlopen(
                Request(
                    endpoint,
                    data=b'{"latency_ms":0,"error_rate":0}',
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ) as response:
                if json.load(response) != {"latency_ms": 0, "error_rate": 0}:
                    raise RuntimeError("watchdog reset not confirmed")
    else:
        container = f"rca-petclinic-acceptance-{args.service}-1"
        project = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                container,
            ],
            text=True,
            timeout=10,
        ).strip()
        if project != "rca-petclinic-acceptance":
            raise RuntimeError("wrong teaching project")
        paused = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Paused}}", container],
            text=True,
            timeout=10,
        ).strip()
        if paused == "true":
            subprocess.run(
                ["docker", "unpause", container],
                check=True,
                capture_output=True,
                timeout=10,
            )


if __name__ == "__main__":
    main()
