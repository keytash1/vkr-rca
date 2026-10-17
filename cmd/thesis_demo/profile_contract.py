"""Versioned telemetry meaning; no fitting or inference code.

A profile cannot inherit healthy expectations from different queries, units,
identity mapping, sources or trace API. Historical unbound baselines are marked,
not retroactively certified.
"""

import hashlib
import json

from rca_ml.m12_adapter import CANONICAL_UNITS

CONTRACT_VERSION = "telemetry-profile-contract-v1"


def semantic_contract(profile):
    return {
        "version": CONTRACT_VERSION,
        "candidate_services": list(profile.services),
        "aliases": profile.aliases,
        "ignored_service_labels": sorted(profile.ignored_service_labels),
        "metrics": {
            "url": profile.metrics_url,
            "queries": profile.metric_queries,
            "service_label": profile.metric_service_label,
            "step_seconds": profile.query_step_seconds,
            "canonical_units": CANONICAL_UNITS,
            "semantic_map": profile.semantic_map,
        },
        "traces": {
            "url": profile.traces_url,
            "api": profile.trace_contract,
            "query_services": sorted(set(profile.trace_query_services)),
        },
        "workload": {"fixed_rps": profile.fixed_rps, "query": profile.rps_query},
    }


def contract_sha256(profile):
    return hashlib.sha256(
        json.dumps(
            semantic_contract(profile),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def validate_semantic_map(value):
    if not isinstance(value, dict) or set(value) != set(CANONICAL_UNITS):
        raise ValueError(
            "semantic map must describe the four canonical metric families"
        )
    for family, spec in value.items():
        if not isinstance(spec, dict) or set(spec) != {
            "source_kind",
            "source_unit",
            "canonical_unit",
            "transformation",
            "replica_aggregation",
            "counter_reset_policy",
        }:
            raise ValueError(f"invalid semantic map: {family}")
        if spec["source_kind"] not in {"counter", "gauge", "derived"}:
            raise ValueError(f"invalid metric source kind: {family}")
        if spec["canonical_unit"] != CANONICAL_UNITS[family]:
            raise ValueError(f"canonical unit differs: {family}")
        for key in (
            "source_unit",
            "transformation",
            "replica_aggregation",
            "counter_reset_policy",
        ):
            if (
                not isinstance(spec[key], str)
                or not spec[key].strip()
                or len(spec[key]) > 1000
            ):
                raise ValueError(f"semantic map requires an explicit {key}: {family}")
        if (
            spec["source_kind"] == "counter"
            and spec["counter_reset_policy"] == "not_applicable"
        ):
            raise ValueError(f"counter reset handling must be declared: {family}")
    return value


def baseline_binding(profile):
    path = profile.artifact_dir / "provenance.json"
    if not path.is_file():
        return {"state": "needs_review", "reason": "legacy_baseline_without_provenance"}
    provenance = json.loads(path.read_text())
    expected = provenance.get("profile_contract_sha256")
    if expected is None:
        return {
            "state": "needs_review",
            "reason": "legacy_baseline_without_semantic_binding",
        }
    if expected != contract_sha256(profile):
        raise ValueError(
            "baseline/profile semantic contract differs; prepare and activate a matching baseline"
        )
    required = {"healthy-baseline.json", "legacy-metric-baseline.json"}
    if set(provenance.get("files_sha256", {})) != required:
        raise ValueError("bound baseline requires both file checksums")
    for name, expected_hash in provenance["files_sha256"].items():
        if (
            hashlib.sha256((profile.artifact_dir / name).read_bytes()).hexdigest()
            != expected_hash
        ):
            raise ValueError(f"healthy baseline checksum differs: {name}")
    return {
        "state": "active",
        "reason": "semantic_contract_and_checksums_match",
        "profile_contract_sha256": expected,
        "healthy_end_unix": provenance.get("healthy_end_unix"),
    }
