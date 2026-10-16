"""Regression of a minimal installed runtime against separately mounted sealed inputs.

The reference corpus is a test fixture, not part of the product image. Labels
are read only by the comparator; only truth-free windows enter inference.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys


def run(root: Path, reference: Path, minimum: int) -> dict:
    sys.path[:0] = [str(root / "cmd/thesis_demo"), str(root / "ml")]
    from profile_runtime import ProfileTransferRuntime
    from server import DiagnosticApplication
    import numpy
    import xgboost
    run_dir = reference / "external-data/m14/runs/locked-v1"
    index = run_dir / "locked/telemetry-index.jsonl"
    if not index.is_file():
        run_dir = reference / "deploy/product/replay"
        index = run_dir / "index.jsonl"
    entries = [json.loads(line) for line in index.read_text().splitlines() if line]
    expected = json.loads((reference / "ml/models/m14/evaluation-inputs.json").read_text())["predictions"]["frozen_m13"]
    if len(entries) < minimum:
        raise ValueError("insufficient available reference cases")
    runtime = None
    checked = []
    for entry in sorted(entries, key=lambda x: x["incident_id"]):
        raw = (run_dir / entry["telemetry_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("reference input checksum differs")
        incident = {k: v for k, v in json.loads(raw).items() if k != "workload_result"}
        if runtime is None:
            runtime = ProfileTransferRuntime(root, reference / "ml/models/m14", tuple(incident["candidate_services"]))
        app = DiagnosticApplication.__new__(DiagnosticApplication)
        actual = app.analyze(incident, runtime)["candidates"]
        got = [(p["rank"], p["service"], p["model_score"]) for p in actual]
        want = [(p["rank"], p["service"], p["score"]) for p in expected[entry["incident_id"]]]
        if got != want:
            raise RuntimeError("installed runtime changed sealed rank or score: " + entry["incident_id"])
        checked.append(entry["incident_id"])
    if "rca_ml.m14_runtime" in sys.modules or (root / "ml/models/m14").exists():
        raise RuntimeError("minimal runtime unexpectedly contains or imports experiment installation")
    return {"purpose": "INSTALLATION_REGRESSION_NOT_NEW_ACCURACY_EVALUATION",
            "status": "passed", "cases": len(checked), "all_ranks_and_scores_exact": True,
            "python": platform.python_version(), "platform": platform.platform(),
            "numpy": numpy.__version__, "xgboost": xgboost.__version__,
            "experiment_runtime_imported": False, "case_ids": checked}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--minimum-cases", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.root.resolve(), args.reference_root.resolve(), args.minimum_cases)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "case_ids"}))
