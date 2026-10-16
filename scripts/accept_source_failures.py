"""Stop/restart only this project's real sources and exercise the product API.

This is an engineering failure-handling check, not an RCA accuracy experiment.
All stopped services are restarted in finally blocks. Do not run on other stacks.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]
from server import DiagnosticApplication, make_handler

PROJECTS = {
    "local-three": ("rca-product-acceptance", "deploy/acceptance/compose.yml", "local-three-run-4"),
    "petclinic": ("rca-petclinic-acceptance", "deploy/acceptance/petclinic/compose.yml", "petclinic-run-4"),
}


def request(url, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    try:
        response = urlopen(Request(url, data=body, headers={"Content-Type": "application/json"} if body else {}), timeout=140)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def wait_ready(url):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        try:
            if request(url)[0] == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"source was not restored: {url}")


def main(output, profile_id):
    if output.exists():
        raise ValueError("refusing to overwrite acceptance record")
    app = DiagnosticApplication(ROOT, ROOT / "deploy/acceptance/profiles")
    project, compose_file, reference = PROJECTS[profile_id]
    compose = ["/opt/homebrew/bin/docker", "compose", "-f", str(ROOT / compose_file)]
    profile = app.profiles[profile_id]
    count = len(profile.services)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/analyze"
    interval = json.loads((ROOT / "docs/product-acceptance" / reference / "intervals.json").read_text())
    payload = {"profile_id": profile_id, "start_unix": interval["start_unix"], "end_unix": interval["end_unix"]}
    results = {}
    try:
        status, result = request(url, payload)
        if status != 200 or result["candidate_count"] != count:
            raise RuntimeError("initial real-source analysis failed")
        results["before"] = {"http_status": status, "result": result}
        for source in ("prometheus", "jaeger"):
            try:
                subprocess.run(compose + ["stop", "-t", "2", source], check=True, capture_output=True)
                status, result = request(url, payload)
                results[source + "_stopped"] = {"http_status": status, "result": result}
                if source == "prometheus":
                    if status != 502 or result["code"] != "TELEMETRY_UNAVAILABLE" or "candidates" in result:
                        raise RuntimeError("metric source failure produced an incorrect response")
                elif status != 200 or result["source_status"]["traces"] != "unavailable" or result["candidate_count"] != count:
                    raise RuntimeError("trace source failure was not exposed as degraded data")
            finally:
                subprocess.run(compose + ["start", source], check=True, capture_output=True)
                wait_ready(profile.metrics_url + "/api/v1/status/buildinfo" if source == "prometheus" else profile.traces_url + "/api/services")
            status, result = request(url, payload)
            results[source + "_restored"] = {"http_status": status, "result": result}
            if status != 200 or result["candidate_count"] != count or result["source_status"]["traces"] != "available":
                raise RuntimeError("restoring source did not restore the API path")
        record = {"status": "PASSED_REAL_SOURCE_FAILURE_RECOVERY", "project": project,
                  "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "cases": results,
                  "scope": "Required metrics fail closed; unavailable traces remain explicit; recovery requires no application restart. No accuracy claim."}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        print(json.dumps({"status": record["status"], "output": str(output)}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile-id", choices=sorted(PROJECTS), default="local-three")
    args = parser.parse_args()
    main(args.output, args.profile_id)
