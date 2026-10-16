"""Capture or verify the immutable research boundary before product changes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]


def snapshot() -> dict:
    from server import DiagnosticApplication
    import numpy
    import xgboost

    tracked = subprocess.check_output(
        ["git", "ls-files", "ml/models"], cwd=ROOT, text=True,
    ).splitlines()
    app = DiagnosticApplication(ROOT)
    expected = json.loads((ROOT / "ml/models/m14/evaluation-inputs.json").read_text())
    predictions = expected["predictions"]["frozen_m13"]
    checked = []
    for case_id in sorted(app.examples):
        incident = {k: v for k, v in app.example(case_id).items() if k != "workload_result"}
        actual = app.analyze(incident)["candidates"]
        got = [(x["rank"], x["service"], x["model_score"]) for x in actual]
        want = [(x["rank"], x["service"], x["score"]) for x in predictions[case_id]]
        if got != want:
            raise RuntimeError(f"sealed ranking differs: {case_id}")
        checked.append(case_id)
    return {
        "purpose": "PRODUCT_REGRESSION_ONLY_NO_MODEL_SELECTION",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": platform.python_version(), "numpy": numpy.__version__,
        "xgboost": xgboost.__version__,
        "model_and_research_artifacts_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in tracked
        },
        "sealed_replay_cases": checked,
        "sealed_predictions_sha256": hashlib.sha256(
            json.dumps(predictions, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if bool(args.capture) == bool(args.verify):
        parser.error("select exactly one of --capture or --verify")
    value = snapshot()
    if args.capture:
        args.capture.parent.mkdir(parents=True, exist_ok=True)
        with args.capture.open("x") as target:
            json.dump(value, target, indent=2, ensure_ascii=False, sort_keys=True)
            target.write("\n")
    else:
        old = json.loads(args.verify.read_text())
        for key in ("model_and_research_artifacts_sha256", "sealed_replay_cases", "sealed_predictions_sha256"):
            if old[key] != value[key]:
                raise RuntimeError(f"regression boundary differs: {key}")
    print(json.dumps({"status": "ok", "cases": len(value["sealed_replay_cases"]),
                      "artifact_files": len(value["model_and_research_artifacts_sha256"])}))


if __name__ == "__main__":
    main()
