"""Preserve bounded raw wire responses for the existing, unmodified pilot.

No new faults or model calls. Original source failures stay in the original
results. A later decoder replay is a separate engineering diagnosis.
"""
import json
import sys
import time

from r3_metric_reserve_preflight import ROOT, PRIVATE, SERVICES, get, save
sys.path.insert(0, str(ROOT.parent / "rca-workbench/cmd/thesis_demo"))
from live_sources import LiveProfile, _jaeger_interval


def run():
    profile = LiveProfile.load(PRIVATE / "profile.json", ROOT)
    deadline = time.monotonic() + 1200
    completed = set()
    while len(completed) < 12 and time.monotonic() < deadline:
        for i in range(1, 13):
            name = f"p-{i:03}"
            path = PRIVATE / name / "window.json"
            output = PRIVATE / name / "raw-traces.json"
            if name in completed or not path.is_file():
                continue
            if output.exists():
                completed.add(name)
                continue
            window = json.loads(path.read_text())
            raw = []
            budget = [16]
            for service in SERVICES:
                raw.extend(_jaeger_interval(profile, service, window["start_unix"],
                                            window["end_unix"], budget, time.monotonic()+30))
            if len(json.dumps(raw).encode()) > 8 * 1024 * 1024:
                raise ValueError("wire diagnostic case exceeds 8 MiB")
            save(output, {"data": raw, "query_start": window["start_unix"],
                          "query_end": window["end_unix"], "captured_at": time.time(),
                          "role": "POST_CAPTURE_WIRE_DIAGNOSIS_NOT_REPLACEMENT"})
            completed.add(name)
            print("raw wire saved", name, "trace records", len(raw), flush=True)
        time.sleep(2)
    print("wire snapshots", len(completed), "no new incidents", flush=True)


if __name__ == "__main__":
    run()
