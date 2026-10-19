"""Operator-only onboarding: inspect -> prepare -> activate/rollback.

No HTTP configuration write or automatic candidate deletion. Discovery produces
a proposal; only the integrator can confirm logical identities and metric
meaning. Atomic activation preserves a previous profile for explicit rollback.
Restart the diagnostic process after activation to load the new runtime.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from live_sources import (
    LiveProfile,
    _bounded_collection,
    _prometheus,
    MAX_COLLECTION_SECONDS,
)
from profile_check import parse_time
from profile_contract import baseline_binding, contract_sha256
from profile_setup import prepare


def sha(data):
    return hashlib.sha256(data).hexdigest()


@_bounded_collection
def inspect_profile(root, path, start, end):
    if not 0 < end - start <= 3600 or end > time.time():
        raise ValueError("inspection needs a past interval of at most one hour")
    profile = LiveProfile.load(path, root, require_artifacts=False)
    observed, annotations = {}, []
    deadline = time.monotonic() + MAX_COLLECTION_SECONDS
    for family, query in profile.metric_queries.items():
        for series in _prometheus(
            profile, query, start, end, deadline, annotations, family
        ):
            label = series.get("metric", {}).get(profile.metric_service_label)
            if not isinstance(label, str) or not label or len(label) > 512:
                raise ValueError("discovery returned a missing/invalid service label")
            if label in profile.ignored_service_labels:
                continue
            logical = profile.aliases.get(label, label)
            observed.setdefault(logical, set()).add(family)
    known, found = set(profile.services), set(observed)
    report = {
        "schema_version": "onboarding-inspection-v1",
        "state": "draft",
        "profile_id": profile.id,
        "profile_contract_sha256": contract_sha256(profile),
        "start_unix": start,
        "end_unix": end,
        "configured_candidates": sorted(known),
        "proposed_candidates": sorted(known | found),
        "unmapped_observed_services": sorted(found - known),
        "configured_services_not_observed": sorted(known - found),
        "metric_families_by_observed_service": {
            s: sorted(v) for s, v in sorted(observed.items())
        },
        "annotations": annotations,
        "semantic_map_declared": profile.semantic_map is not None,
        "requires_integrator_review": [
            "logical services and aliases",
            "replica aggregation",
            "source units and transformations",
            "counter reset handling",
            "healthy interval",
        ],
        "notice": "Observed labels are proposals, not an authoritative inventory. Missing services remain candidates. No files or runtime state were changed.",
    }
    if profile.http_observations_config is not None:
        from http_observations import collect_http, unavailable
        try:
            report["http_observations"] = collect_http(profile, start, end)
        except Exception:
            report["http_observations"] = unavailable(profile.services, "HTTP_PROJECTION_UNAVAILABLE", start=start, end=end)
        report["requires_integrator_review"].append("optional HTTP business scope, units and histogram aggregation")
    return report


def _inside(root, path):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(
            "operator profile path must be a non-symlink inside the installation"
        )
    return path.resolve()


def activate(root, draft_path, active_path, expected_sha256):
    root = root.resolve()
    draft = _inside(root, draft_path)
    active = _inside(root, active_path)
    if draft == active:
        raise ValueError("draft and active profile paths must differ")
    initial_data = draft.read_bytes()
    profile = LiveProfile.load(draft, root)
    if draft.read_bytes() != initial_data:
        raise ValueError("draft profile changed during validation")
    if profile.semantic_map is None:
        raise ValueError("activation requires the reviewed four-family semantic map")
    binding = baseline_binding(profile)
    if binding["state"] != "active":
        raise ValueError("activation requires a semantically bound baseline")
    if active.stem != profile.id:
        raise ValueError("active filename must match profile id")
    active.parent.mkdir(parents=True, exist_ok=True)
    with (active.parent / ".profile-activation.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if active.is_symlink():
            raise ValueError("active profile must not be a symlink")
        old = active.read_bytes() if active.exists() else None
        actual = sha(old) if old is not None else "absent"
        if actual != expected_sha256:
            raise ValueError(
                "active profile changed; inspect it again before activation"
            )
        if old is not None and json.loads(old).get("id") != profile.id:
            raise ValueError("cannot replace a different profile identity")
        data = initial_data
        # Re-validate the exact bytes immediately before committing them.
        if sha(data) != sha(draft.read_bytes()):
            raise ValueError("draft profile changed during activation")
        history = active.parent / ".profile-history" / profile.id
        if not history.resolve().is_relative_to(root):
            raise ValueError("profile history must remain inside the installation")
        history.mkdir(parents=True, exist_ok=True)
        if old is not None:
            backup = history / f"{actual}.json"
            if backup.exists() and backup.read_bytes() != old:
                raise ValueError("profile history checksum conflict")
            if not backup.exists():
                with backup.open("xb") as target:
                    target.write(old)
        with tempfile.NamedTemporaryFile(
            dir=active.parent, prefix=".profile-", delete=False
        ) as target:
            temporary = Path(target.name)
            try:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
                # All cooperating activations use this directory lock.
                os.replace(temporary, active)
                directory_fd = os.open(active.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
        return {
            "state": "active_after_process_restart",
            "profile_id": profile.id,
            "profile_contract_sha256": contract_sha256(profile),
            "previous_profile_sha256": actual,
            "active_profile_sha256": sha(data),
            "rollback_profile": str(history / f"{actual}.json")
            if old is not None
            else None,
            "artifact_dir": str(profile.artifact_dir),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Read-only inventory/coverage proposal")
    inspect.add_argument("--profile", type=Path, required=True)
    inspect.add_argument("--start", required=True)
    inspect.add_argument("--end", required=True)
    inspect.add_argument("--output", type=Path, required=True)
    build = sub.add_parser(
        "prepare", help="Create a new baseline; never overwrite the old one"
    )
    build.add_argument("--profile", type=Path, required=True)
    build.add_argument("--start", required=True)
    build.add_argument("--end", required=True)
    build.add_argument("--confirm-healthy", action="store_true", required=True)
    switch = sub.add_parser(
        "activate", help="Activate a draft or previously saved rollback profile"
    )
    switch.add_argument("--draft", type=Path, required=True)
    switch.add_argument("--active", type=Path, required=True)
    switch.add_argument(
        "--expect-active-sha256",
        required=True,
        help="Exact current file hash or absent",
    )
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_profile(
                args.root.resolve(),
                args.profile,
                parse_time(args.start),
                parse_time(args.end),
            )
            with args.output.open("x") as output:
                output.write(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n"
                )
        elif args.command == "prepare":
            profile = LiveProfile.load(
                args.profile, args.root.resolve(), require_artifacts=False
            )
            if profile.semantic_map is None:
                raise ValueError(
                    "declare and review the semantic map before preparation"
                )
            result = prepare(
                args.root, args.profile, parse_time(args.start), parse_time(args.end)
            )
        else:
            result = activate(
                args.root, args.draft, args.active, args.expect_active_sha256
            )
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
