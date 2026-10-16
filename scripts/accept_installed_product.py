"""Compare a separately installed HTTP product with native calculation on real data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "cmd/thesis_demo")]
from live_sources import LiveProfile, collect
from profile_runtime import ProfileTransferRuntime
from server import DiagnosticApplication


def request(url: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    with urlopen(Request(url, data=body, headers=headers), timeout=150) as response:
        return json.load(response)


def run(url: str, profile_path: Path, baseline: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    profile = LiveProfile.load(profile_path.resolve(), ROOT, require_artifacts=False)
    end = int(time.time()) // profile.query_step_seconds * profile.query_step_seconds - 60
    start = end - 120
    window, source = collect(profile, start, end)
    runtime = ProfileTransferRuntime(ROOT, baseline.resolve(), profile.services)
    app = DiagnosticApplication.__new__(DiagnosticApplication)
    expected = app.analyze(window, runtime)
    payload = {"profile_id": profile.id, "start_unix": start, "end_unix": end}
    actual = request(url.rstrip("/") + "/api/analyze", payload)
    # Ignore unique result ID, collection timestamps and profile's host URLs.
    # Candidate entries include raw observations, coverage and diagnostic values.
    if actual["candidates"] != expected["candidates"]:
        raise RuntimeError("installed/native candidates, scores or observations differ")
    if actual["input_sha256"] != source["input_sha256"]:
        raise RuntimeError("installed/native canonical inputs differ")
    health = request(url.rstrip("/") + "/api/health")
    if health["experiment_available"] or health["examples"] or health["profile_errors"]:
        raise RuntimeError("unexpected research dependency or invalid profile")
    summary = {"purpose": "INSTALLATION_ACCEPTANCE_NOT_ACCURACY_EXPERIMENT",
               "status": "passed", "request": payload, "candidate_count": len(actual["candidates"]),
               "all_candidates_scores_and_observations_exact": True,
               "canonical_input_hash_exact": True, "input_sha256": actual["input_sha256"],
               "result_id": actual["result_id"], "timing": actual["timing"], "health": health,
               "source_status": actual["source_status"]}
    for name, data in (("summary", summary), ("live-result", actual), ("canonical-window", window)):
        (output / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_status"}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.profile, args.baseline_dir, args.output)
