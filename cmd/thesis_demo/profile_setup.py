"""Prepare a new system profile from an unlabeled healthy interval.

This command does not fit or modify any frozen LambdaMART model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from live_sources import FAMILIES, LiveProfile, baseline_issues, collect
from profile_contract import contract_sha256, semantic_contract
from rca_ml.m12_adapter import robust_baseline
from rca_ml.m13_features import fit_healthy_baseline


def _utc(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc).timestamp()


def prepare(root: Path, profile_path: Path, start: float, end: float) -> dict:
    root = root.resolve()
    profile = LiveProfile.load(profile_path, root, require_artifacts=False)
    allowed = (root / "deploy/profiles/artifacts").resolve()
    if not profile.artifact_dir.is_relative_to(allowed):
        raise ValueError("new healthy artifacts must be under deploy/profiles/artifacts")
    if profile.artifact_dir.exists():
        raise FileExistsError(f"refusing to replace existing baseline: {profile.artifact_dir}")
    if end - start < 60:
        raise ValueError("healthy interval must be at least 60 seconds")
    window, status = collect(profile, start, end)
    issues = baseline_issues(profile, window, status, start, end)
    if issues:
        raise ValueError("; ".join(issues))
    if status["traces"] != "available" or not window["traces"]:
        raise ValueError("healthy trace source is unavailable or empty")
    missing = {
        service: sorted(set(FAMILIES) - set(status["metric_families_by_service"][service]))
        for service in profile.services
    }
    missing = {service: families for service, families in missing.items() if families}
    if missing:
        raise ValueError(f"healthy metrics are incomplete: {missing}")
    healthy = {
        "segments": [{
            "start_unix": start, "end_unix": end,
            "requests_per_second": window["requests_per_second"],
        }],
        "metrics": window["metrics"],
        "traces": window["traces"],
    }
    baseline = fit_healthy_baseline(healthy, profile.services)
    legacy = robust_baseline(window["metrics"])
    if not baseline["windows"]:
        raise ValueError("healthy interval did not produce baseline windows")
    outputs = {
        "healthy-baseline.json": baseline,
        "legacy-metric-baseline.json": legacy,
        "provenance.json": {
            "profile_id": profile.id, "profile_version": profile.version,
            "healthy_start_unix": start, "healthy_end_unix": end,
            "metric_sample_count": len(window["metrics"]),
            "span_count": len(window["traces"]),
            "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            "profile_contract_sha256": contract_sha256(profile),
            "profile_contract": semantic_contract(profile),
            "role": "UNLABELED_HEALTHY_ENGINEERING",
        },
    }
    outputs["provenance.json"]["files_sha256"] = {
        name: hashlib.sha256((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
        for name, value in outputs.items() if name != "provenance.json"
    }
    outputs["provenance.json"]["source_status"] = status
    profile.artifact_dir.mkdir(parents=True, exist_ok=False)
    for name, value in outputs.items():
        (profile.artifact_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
    return outputs["provenance.json"] | {"artifact_dir": str(profile.artifact_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit profile-specific healthy expectations")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--start", required=True, help="ISO-8601 with timezone")
    parser.add_argument("--end", required=True, help="ISO-8601 with timezone")
    args = parser.parse_args()
    try:
        result = prepare(args.root, args.profile, _utc(args.start), _utc(args.end))
    except (ValueError, FileExistsError, OSError) as error:
        parser.exit(2, f"{error}\n")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
