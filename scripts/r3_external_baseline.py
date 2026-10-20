"""One fixed, post-hoc upstream BARO comparison; predict never opens truth."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REVISION = "405c8fd24071af41ceb4b3aabb451e5e3e15d6c6"
FAMILIES = ("cpu", "memory", "network", "traffic_rate")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def matrix(records, services):
    """Lossless pivot only: reject unknown, duplicate, missing/nonfinite values."""
    import pandas as pd
    if len(set(services)) != len(services) or not services:
        raise ValueError("duplicate/empty candidate universe")
    mapping = {f"c{i:04d}_{f}": s for i, s in enumerate(services) for f in FAMILIES}
    columns = {(s, f): c for c, (s, f) in zip(mapping, ((s, f) for s in services for f in FAMILIES))}
    expected_units = {"cpu": "cores", "memory": "bytes", "network": "bytes_per_second",
                      "traffic_rate": "bytes_per_second"}
    rows = {}
    for item in records:
        key = (item["service"], item["family"])
        if key not in columns or item["unit"] != expected_units[item["family"]]:
            raise ValueError("unsupported metric or unit")
        timestamp, value = float(item["timestamp"]), float(item["value"])
        if not math.isfinite(timestamp) or not math.isfinite(value):
            raise ValueError("nonfinite metric")
        row = rows.setdefault(timestamp, {})
        col = columns[key]
        if col in row:
            raise ValueError("duplicate metric point")
        row[col] = value
    if not rows or any(set(row) != set(mapping) for row in rows.values()):
        raise ValueError("incomplete metric grid; no imputation allowed")
    frame = pd.DataFrame([{"time": t, **rows[t]} for t in sorted(rows)])
    return frame[["time", *mapping]], mapping


def project(native, mapping):
    services = []
    for column in native:
        if column not in mapping:
            raise ValueError("upstream returned unknown column")
        service = mapping[column]
        if service not in services:
            services.append(service)
    return [{"service": service, "rank": i} for i, service in enumerate(services, 1)]


def predict(output):
    import pandas as pd
    source = ROOT / "external-data/RCAEval-source"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise ValueError("unexpected upstream revision")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True):
        raise ValueError("upstream checkout is not clean")
    sys.path.insert(0, str(source))
    # Load the unchanged entrypoint directly, avoiding unrelated e2e method imports.
    module_path = source / "RCAEval/e2e/baro.py"
    spec = importlib.util.spec_from_file_location("r3l_pinned_baro", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = ROOT / "external-data/m14/runs/locked-v1"
    healthy_path = run / "healthy/baseline.json"
    healthy = json.loads(healthy_path.read_text())
    paths = sorted((run / "locked/telemetry").glob("*.json"))
    if len(paths) != 50:
        raise ValueError("expected exactly the 50 original windows")
    receipt = {"protocol_sha256": sha(ROOT / "docs/R3_EXTERNAL_BASELINE_PROTOCOL.md"),
               "data_role": "USED_TEST_POST_HOC", "upstream_revision": revision,
               "source_sha256": {str(p.relative_to(source)): sha(p) for p in
                   (module_path, source / "RCAEval/io/time_series.py")},
               "healthy_sha256": sha(healthy_path), "fit_count": 0,
               "versions": {p: importlib.metadata.version(p) for p in
                            ("numpy", "pandas", "scikit-learn")},
               "python": sys.version, "cases": [], "truth_read": False}

    def expired(_signal, _frame):
        raise TimeoutError("30 second BARO call budget exceeded")

    old_handler = signal.signal(signal.SIGALRM, expired)
    try:
        for path in paths:
            # No truth/plan/evaluation file is accessed in this phase.
            window = json.loads(path.read_text())
            services = window["candidate_services"]
            row = {"incident_id": window["incident_id"], "input_sha256": sha(path),
                   "candidate_services": services, "ranking": []}
            started = time.monotonic()
            try:
                if len(services) != 12:
                    raise ValueError("expected original 12 candidate services")
                base, mapping = matrix(healthy["metrics"], services)
                incident, incident_mapping = matrix(window["metrics"], services)
                if mapping != incident_mapping or base.time.max() >= incident.time.min():
                    raise ValueError("inconsistent mapping/overlapping healthy period")
                frame = pd.concat([base, incident], ignore_index=True)
                boundary = float(window["start_unix"])
                row["points"] = {"healthy": len(base), "incident": len(incident),
                                 "incident_points_before_boundary": int((incident.time < boundary).sum())}
                signal.alarm(30)
                result = module.baro(frame, inject_time=boundary, dataset="astronomy-shop",
                                     dk_select_useful=False)
                row["ranking"] = project(result["ranks"], mapping)
                row["status"] = "success"
            except Exception as error:
                row["status"] = "failure"
                row["error"] = f"{type(error).__name__}: {error}"
            finally:
                signal.alarm(0)
            row["seconds_including_pivot"] = time.monotonic() - started
            receipt["cases"].append(row)
            print(f"{len(receipt['cases'])}/50 {row['status']}", flush=True)
    finally:
        signal.signal(signal.SIGALRM, old_handler)
    write_new(output, receipt)


def evaluate(predictions, output):
    sys.path.insert(0, str(ROOT / "ml"))
    from rca_ml.m13_protocol import paired_bootstrap, ranking_metrics, cluster_key
    receipt = json.loads(predictions.read_text())
    original_path = ROOT / "ml/models/m14/evaluation-inputs.json"
    original = json.loads(original_path.read_text())
    truth = {row["incident_id"]: row for row in original["truth"]}
    external = {row["incident_id"]: row["ranking"] for row in receipt["cases"]}
    if len(receipt["cases"]) != 50 or set(external) != set(truth):
        raise ValueError("same-case denominator mismatch")
    rankings = {**original["predictions"], "upstream_baro": external}
    if any(set(value) != set(truth) for value in rankings.values()):
        raise ValueError("original denominator mismatch")
    summary = {"data_role": "USED_TEST_POST_HOC", "predictions_sha256": sha(predictions),
               "original_evaluation_inputs_sha256": sha(original_path), "n": len(truth),
               "clusters": len({cluster_key(row) for row in truth.values()}),
               "successes": sum(row["status"] == "success" for row in receipt["cases"]),
               "metrics": {name: ranking_metrics(value, truth) for name, value in rankings.items()},
               "ensemble_minus_baro": {metric: paired_bootstrap(rankings["frozen_m13"], external,
                   truth, metric, cluster=True, seed=20261020) for metric in
                   ("ac_at_1", "ac_at_3", "ac_at_5", "mrr")},
               "no_model_promotion": True}
    write_new(output, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("predict", "evaluate"))
    parser.add_argument("--predictions", type=Path, default=ROOT / "artifacts/r3-external-baseline-v1/predictions.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "predict":
        predict(args.output)
    else:
        evaluate(args.predictions, args.output)
