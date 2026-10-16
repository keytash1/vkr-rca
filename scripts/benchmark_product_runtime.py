"""Measure prepared-window calculation capacity, not diagnostic accuracy or source latency."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]
from profile_runtime import ProfileTransferRuntime
from server import DiagnosticApplication
from rca_ml.m12_adapter import CANONICAL_UNITS, robust_baseline
from rca_ml.m13_features import fit_healthy_baseline


def window(service_count: int, seconds: int) -> dict:
    services = [f"capacity-{index:02d}" for index in range(service_count)]
    start = 1_700_000_000
    metrics, spans = [], []
    magnitudes = {"cpu": .05, "memory": 100_000_000, "network": 20000, "traffic_rate": 8000}
    for second in range(seconds + 1):
        for index, service in enumerate(services):
            for family, unit in CANONICAL_UNITS.items():
                metrics.append({"timestamp": start + second, "service": service,
                                "family": family, "unit": unit,
                                "value": magnitudes[family] * (1 + index / 100 + (second % 7) / 100)})
        if second == seconds:
            continue
        for request in range(3):
            trace_id = f"capacity-{second}-{request}"
            for index, service in enumerate(services):
                spans.append({"trace_id": trace_id, "span_id": str(index),
                              "parent_span_id": str(index - 1) if index else "",
                              "service": service, "peer_service": services[index - 1] if index else "",
                              "start_time_us": (start + second) * 1_000_000 + request * 100_000 + index * 100,
                              "duration_us": 50_000 - index * 200, "span_kind": "SERVER", "error": False,
                              "observed_edge": {"source": services[index - 1], "target": service} if index else None})
    return {"incident_id": "synthetic-capacity-only", "start_unix": start,
            "end_unix": start + seconds, "candidate_services": services,
            "requests_per_second": 3., "metrics": metrics, "traces": spans, "traces_collected": True}


def run(repetitions: int) -> dict:
    healthy, incident = window(20, 120), window(20, 60)
    services = tuple(incident["candidate_services"])
    prepared = {"segments": [{"start_unix": healthy["start_unix"], "end_unix": healthy["end_unix"],
                              "requests_per_second": healthy["requests_per_second"]}],
                "metrics": healthy["metrics"], "traces": healthy["traces"]}
    with tempfile.TemporaryDirectory(prefix="rca-capacity-") as temporary:
        artifact = Path(temporary)
        (artifact / "healthy-baseline.json").write_text(json.dumps(fit_healthy_baseline(prepared, services)))
        (artifact / "legacy-metric-baseline.json").write_text(json.dumps(robust_baseline(healthy["metrics"])))
        started = time.perf_counter()
        runtime = ProfileTransferRuntime(ROOT, artifact, services)
        load_seconds = time.perf_counter() - started
        app = DiagnosticApplication.__new__(DiagnosticApplication)
        samples = []
        for _ in range(repetitions + 1):
            started = time.perf_counter()
            result = app.analyze(incident, runtime)
            samples.append(time.perf_counter() - started)
            assert len(result["candidates"]) == 20
            assert {p["service"] for p in result["candidates"]} == set(services)
            assert all(math.isfinite(p["model_score"]) for p in result["candidates"])
    warm = samples[1:]
    hardware = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}
    if sys.platform == "darwin":
        for key in ("machdep.cpu.brand_string", "hw.memsize", "hw.ncpu"):
            hardware[key] = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
    return {"purpose": "SYNTHETIC_20_CANDIDATE_CALCULATION_CAPACITY_NOT_ACCURACY",
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "hardware": hardware, "candidate_count": 20,
            "metric_points": len(incident["metrics"]), "spans": len(incident["traces"]),
            "input_sha256": hashlib.sha256(json.dumps(incident, sort_keys=True).encode()).hexdigest(),
            "model_load_seconds": load_seconds, "first_calculation_seconds": samples[0],
            "warm_repetitions": repetitions, "warm_median_seconds": statistics.median(warm),
            "warm_p95_seconds": sorted(warm)[math.ceil(.95 * len(warm)) - 1],
            "warm_max_seconds": max(warm), "calculation_seconds": samples,
            "limit_seconds": 5., "passed": max(samples) <= 5.,
            "scope": "Features, base-ranking context, ensemble, observations and response object; "
                     "excludes model loading, baseline preparation, telemetry collection and HTTP transfer."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=30)
    args = parser.parse_args()
    if args.repetitions < 20 or args.repetitions > 100:
        parser.error("repetitions must be between 20 and 100")
    if args.output.exists():
        parser.error("refusing to overwrite an existing benchmark")
    result = run(args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "first_calculation_seconds", "warm_median_seconds", "warm_max_seconds")}))
