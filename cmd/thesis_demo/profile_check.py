"""Read-only acceptance check for a system's telemetry profile.

This checks source compatibility and coverage, not diagnostic accuracy.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from live_sources import FAMILIES, LiveProfile, baseline_issues, collect


def parse_time(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc).timestamp()


def check_profile(root: Path, profile_path: Path, start: float, end: float,
                  *, baseline: bool = False) -> dict:
    profile = LiveProfile.load(profile_path, root.resolve(), require_artifacts=False)
    started = time.monotonic()
    window, status = collect(profile, start, end)
    missing = {
        service: sorted(set(FAMILIES) - set(status["metric_families_by_service"][service]))
        for service in profile.services
    }
    missing = {service: families for service, families in missing.items() if families}
    issues = []
    if missing:
        issues.append("metric coverage is incomplete for some candidate services")
    if status["traces"] != "available":
        issues.append("trace source is unavailable")
    elif not window["traces"]:
        issues.append("no trace spans were returned for the selected interval")
    if baseline:
        issues.extend(baseline_issues(profile, window, status, start, end))
    elif status.get("annotations"):
        issues.append("metric source returned query annotations; inspect source status")
    if baseline and issues:
        verdict = "not_ready_for_baseline"
    elif issues:
        verdict = "degraded_incident_input"
    else:
        verdict = "ready"
    report = {
        "verdict": verdict,
        "purpose": "baseline" if baseline else "incident",
        "profile_id": profile.id,
        "profile_version": profile.version,
        "candidate_count": len(profile.services),
        "interval_seconds": end - start,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source_status": status,
        "missing_metric_families": missing,
        "issues": issues,
    }
    if profile.http_observations_config is not None:
        from http_observations import collect_http, unavailable
        try:
            report["http_observations"] = collect_http(profile, start, end)
        except Exception:
            report["http_observations"] = unavailable(profile.services, "HTTP_PROJECTION_UNAVAILABLE", start=start, end=end)
        report["elapsed_seconds"] = round(time.monotonic()-started, 3)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a real telemetry profile without changing it")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--start", required=True, help="ISO-8601 with timezone")
    parser.add_argument("--end", required=True, help="ISO-8601 with timezone")
    parser.add_argument("--baseline", action="store_true",
                        help="Require complete metrics and traces for baseline preparation")
    args = parser.parse_args()
    try:
        result = check_profile(args.root, args.profile, parse_time(args.start),
                               parse_time(args.end), baseline=args.baseline)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"verdict": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["verdict"] == "ready" else 1)


if __name__ == "__main__":
    main()
