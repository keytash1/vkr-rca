"""Controlled zero-shot, temporal and repeated-run datasets for M8A."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .dataset import enrich_labels, read_jsonl, sha256_file, write_jsonl
from .generate import GenerationConfig, collect_baseline, prepare_incident, wait_for_samples
from .schema import MODEL_VERSION, SOURCE_FEATURE_SCHEMA_VERSION
from .topology import BenchmarkTopology

M8A_DATASET_SCHEMA = "m8a-v1"
TEMPORAL_PROFILES = ("step_early", "step_late", "ramp", "intermittent", "burst")


@dataclass(frozen=True)
class M8AGenerationConfig:
    seed: int = 20260904
    incidents_per_pair: int = 50
    healthy_controls: int = 50
    baseline_requests: int = 100
    requests_per_incident: int = 20
    concurrency: int = 20
    temporal_repetitions: int = 1
    stability_scenarios: int = 10
    stability_repetitions: int = 5
    drain_seconds: float = 0.25
    collector_settle_seconds: float = 1.25
    poll_interval_seconds: float = 0.2
    poll_timeout_seconds: float = 20.0
    latency_min_ms: int = 1
    latency_max_ms: int = 700
    error_min_rate: float = 0.1
    error_max_rate: float = 1.0

    def runtime(self) -> GenerationConfig:
        return GenerationConfig(
            seed=self.seed,
            incidents_per_pair=self.incidents_per_pair,
            healthy_controls=self.healthy_controls,
            baseline_requests=self.baseline_requests,
            requests_per_incident=self.requests_per_incident,
            concurrency=self.concurrency,
            drain_seconds=self.drain_seconds,
            collector_settle_seconds=self.collector_settle_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            poll_timeout_seconds=self.poll_timeout_seconds,
            latency_min_ms=self.latency_min_ms,
            latency_max_ms=self.latency_max_ms,
            error_min_rate=self.error_min_rate,
            error_max_rate=self.error_max_rate,
        )


def scenarios(topology: BenchmarkTopology, config: M8AGenerationConfig) -> list[dict]:
    randomizer = random.Random(_derived_seed(config.seed, topology.topology_id))
    zero_shot = []
    for root in sorted(topology.services):
        for fault_type in ("latency", "error"):
            for pair_index in range(config.incidents_per_pair):
                if fault_type == "latency":
                    raw = math.exp(randomizer.uniform(math.log(config.latency_min_ms), math.log(config.latency_max_ms)))
                    value: int | float = max(config.latency_min_ms, min(config.latency_max_ms, int(round(raw))))
                else:
                    value = round(randomizer.uniform(config.error_min_rate, config.error_max_rate), 6)
                zero_shot.append(
                    _scenario(
                        topology,
                        config,
                        kind="zero_shot",
                        profile="constant",
                        root=root,
                        fault_type=fault_type,
                        fault_value=value,
                        pair_index=pair_index,
                    )
                )
    for index in range(config.healthy_controls):
        zero_shot.append(
            _scenario(
                topology,
                config,
                kind="zero_shot",
                profile="healthy",
                root=None,
                fault_type="none",
                fault_value=0,
                pair_index=index,
            )
        )
    randomizer.shuffle(zero_shot)

    temporal = []
    for root in sorted(topology.services):
        for fault_type in ("latency", "error"):
            for profile in TEMPORAL_PROFILES:
                for repetition in range(config.temporal_repetitions):
                    temporal.append(
                        _scenario(
                            topology,
                            config,
                            kind="temporal",
                            profile=profile,
                            root=root,
                            fault_type=fault_type,
                            fault_value=_stress_intensity(fault_type, profile),
                            pair_index=repetition,
                        )
                    )

    pairs = [(root, fault_type) for root in sorted(topology.services) for fault_type in ("latency", "error")]
    random.Random(_derived_seed(config.seed + 17, topology.topology_id)).shuffle(pairs)
    stability = []
    for fixed_index, (root, fault_type) in enumerate(pairs[: config.stability_scenarios]):
        fixed_id = f"{topology.topology_id.lower()}-fixed-{fixed_index:02d}"
        for repetition in range(config.stability_repetitions):
            value = 350 if fault_type == "latency" else 0.75
            value = value + fixed_index * 7 if fault_type == "latency" else round(value + fixed_index * 0.01, 6)
            stability.append(
                _scenario(
                    topology,
                    config,
                    kind="stability",
                    profile="step_early",
                    root=root,
                    fault_type=fault_type,
                    fault_value=value,
                    pair_index=repetition,
                    fixed_scenario_id=fixed_id,
                    repetition=repetition,
                )
            )

    result = zero_shot + temporal + stability
    for index, value in enumerate(result):
        value["incident_id"] = f"m8a-{topology.topology_id.lower()}-{index:05d}"
        fingerprint_fields = {key: item for key, item in value.items() if key != "scenario_fingerprint"}
        value["scenario_fingerprint"] = hashlib.sha256(
            json.dumps(fingerprint_fields, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    return result


def generate(
    output_dir: Path,
    topology: BenchmarkTopology,
    config: M8AGenerationConfig,
    frozen_model_path: Path,
) -> dict:
    client = topology.client()
    runtime = config.runtime()
    planned = scenarios(topology, config)
    features_path = output_dir / "features.jsonl"
    labels_path = output_dir / "labels.jsonl"
    if output_dir.exists():
        if (output_dir / "manifest.json").exists():
            raise FileExistsError(f"completed dataset already exists: {output_dir}")
        feature_records = read_jsonl(features_path)
        label_records = read_jsonl(labels_path)
        if len(feature_records) != len(label_records):
            raise ValueError("cannot resume: feature and label counts differ")
        expected = [value["incident_id"] for value in planned[: len(feature_records)]]
        if [value["incident_id"] for value in feature_records] != expected or [
            value["incident_id"] for value in label_records
        ] != expected:
            raise ValueError("cannot resume: incident sequence differs")
        baseline = client.get_json(f"{client.rca}/api/baseline")
        if baseline.get("state") != "frozen":
            raise ValueError("cannot resume without the original frozen baseline")
        start_index = len(feature_records)
        mode = "a"
        started = feature_records[0].get("captured_at", _utc_now()) if feature_records else _utc_now()
        print(f"resuming {topology.topology_id} at {start_index}/{len(planned)}", flush=True)
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        baseline = collect_baseline(client, runtime)
        start_index = 0
        mode = "w"
        started = _utc_now()

    with features_path.open(mode, encoding="utf-8") as feature_output, labels_path.open(
        mode, encoding="utf-8"
    ) as label_output:
        for sequence, scenario in enumerate(planned[start_index:], start_index + 1):
            drain_resets = prepare_incident(client, runtime)
            statuses = Counter()
            segments = _segments(scenario, config.requests_per_incident)
            for segment_index, (enabled, multiplier, count) in enumerate(segments):
                _configure_fault(client, scenario, enabled, multiplier)
                statuses.update(
                    client.send_traffic(
                        f"{scenario['incident_id']}-segment-{segment_index}",
                        count,
                        min(config.concurrency, count),
                    )
                )
            required = (
                sorted(topology.services)
                if scenario["incident_type"] == "healthy"
                else topology.ancestors(str(scenario["root_service"]))
            )
            top_up_cycles = 0

            def top_up(cycle: int) -> None:
                nonlocal top_up_cycles
                top_up_cycles = cycle
                _configure_fault(client, scenario, True, 1.0)
                statuses.update(client.send_traffic(f"{scenario['incident_id']}-topup-{cycle}", 5, 5))

            wait_for_samples(
                client,
                required,
                config.requests_per_incident,
                runtime,
                top_up=top_up if scenario["experiment_kind"] == "zero_shot" else None,
            )
            if scenario["fault_type"] == "error":
                time.sleep(config.collector_settle_seconds)
            snapshot = client.get_json(f"{client.rca}/api/features")
            rankings = client.get_json(f"{client.rca}/api/rca")
            anomalies = client.get_json(f"{client.rca}/api/anomalies")
            feature_record = {
                "incident_id": scenario["incident_id"],
                "captured_at": _utc_now(),
                "feature_snapshot": snapshot,
                "m6_rankings": rankings,
                "m5_anomalies": anomalies,
            }
            feature_output.write(json.dumps(feature_record, sort_keys=True, separators=(",", ":")) + "\n")
            feature_output.flush()
            os.fsync(feature_output.fileno())
            label_record = {
                **scenario,
                "generation_metadata": {
                    "sequence_number": sequence,
                    "traffic_requests": config.requests_per_incident + top_up_cycles * 5,
                    "top_up_cycles": top_up_cycles,
                    "concurrency": config.concurrency,
                    "http_status_counts": dict(sorted(statuses.items())),
                    "drain_resets": drain_resets,
                    "segments": [
                        {"fault_enabled": enabled, "intensity_multiplier": multiplier, "requests": count}
                        for enabled, multiplier, count in segments
                    ],
                },
            }
            label_output.write(json.dumps(label_record, sort_keys=True, separators=(",", ":")) + "\n")
            label_output.flush()
            os.fsync(label_output.fileno())
            if sequence % 10 == 0 or sequence == len(planned):
                print(f"generated {topology.topology_id} {sequence}/{len(planned)}", flush=True)

    client.reset_faults()
    feature_records = read_jsonl(features_path)
    labels = enrich_labels(feature_records, read_jsonl(labels_path))
    write_jsonl(labels_path, labels)
    model_manifest = json.loads((frozen_model_path.parent / "training_manifest.json").read_text(encoding="utf-8"))
    actual_model_hash = sha256_file(frozen_model_path)
    if model_manifest["model_version"] != MODEL_VERSION or model_manifest["model_sha256"] != actual_model_hash:
        raise ValueError("frozen M7 model hash mismatch")
    manifest = {
        "dataset_schema_version": M8A_DATASET_SCHEMA,
        "source_feature_schema_version": SOURCE_FEATURE_SCHEMA_VERSION,
        "run_id": output_dir.name,
        "topology": {
            "id": topology.topology_id,
            "name": topology.name,
            "entry_service": topology.entry_service,
            "services": sorted(topology.services),
            "edges": [list(edge) for edge in topology.edges],
        },
        "git_commit": _git_commit(),
        "generated_at": _utc_now(),
        "generation_started_at": started,
        "random_seed": config.seed,
        "configuration": asdict(config),
        "scenario_counts": dict(sorted(Counter(value["experiment_kind"] for value in planned).items())),
        "zero_shot_fault_incidents": sum(
            value["experiment_kind"] == "zero_shot" and value["incident_type"] == "fault" for value in planned
        ),
        "zero_shot_healthy_controls": sum(value["incident_type"] == "healthy" for value in planned),
        "baseline": baseline,
        "observed_graph": client.get_json(f"{client.rca}/api/graph"),
        "m5_configuration": {
            "latency_z_threshold": 3.5,
            "error_z_threshold": 3.0,
            "current_window_size": 20,
            "minimum_current_samples": 10,
        },
        "frozen_model": {"version": MODEL_VERSION, "sha256": actual_model_hash},
        "python": {"version": platform.python_version()},
        "sha256": {
            "features.jsonl": sha256_file(features_path),
            "labels.jsonl": sha256_file(labels_path),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _scenario(
    topology: BenchmarkTopology,
    config: M8AGenerationConfig,
    *,
    kind: str,
    profile: str,
    root: str | None,
    fault_type: str,
    fault_value: int | float,
    pair_index: int,
    fixed_scenario_id: str | None = None,
    repetition: int | None = None,
) -> dict:
    return {
        "topology_id": topology.topology_id,
        "experiment_kind": kind,
        "incident_type": "healthy" if fault_type == "none" else "fault",
        "temporal_profile": profile,
        "root_service": root,
        "expected_affected_services": [] if root is None else topology.ancestors(root),
        "fault_type": fault_type,
        "fault_value": fault_value,
        "pair_index": pair_index,
        "fixed_scenario_id": fixed_scenario_id,
        "repetition": repetition,
        "generation_seed": config.seed,
    }


def _segments(scenario: dict, total: int) -> list[tuple[bool, float, int]]:
    profile = scenario["temporal_profile"]
    if profile == "healthy":
        return [(False, 0.0, total)]
    if profile in {"constant", "step_early"}:
        return [(True, 1.0, total)]
    half = total // 2
    if profile == "step_late":
        return [(False, 0.0, half), (True, 1.0, total - half)]
    quarter = total // 4
    if profile == "ramp":
        return [(True, multiplier, quarter) for multiplier in (0.25, 0.5, 0.75)] + [
            (True, 1.0, total - 3 * quarter)
        ]
    if profile == "intermittent":
        return [
            (True, 1.0, quarter),
            (False, 0.0, quarter),
            (True, 1.0, quarter),
            (False, 0.0, total - 3 * quarter),
        ]
    if profile == "burst":
        return [(False, 0.0, quarter), (True, 1.0, quarter), (False, 0.0, total - 2 * quarter)]
    raise ValueError(f"unsupported temporal profile {profile!r}")


def _configure_fault(client, scenario: dict, enabled: bool, multiplier: float) -> None:
    root = scenario.get("root_service")
    if root is None or not enabled:
        if root is not None:
            client.set_fault(root)
        return
    if scenario["fault_type"] == "latency":
        client.set_fault(root, latency_ms=max(1, int(round(float(scenario["fault_value"]) * multiplier))))
    else:
        client.set_fault(root, error_rate=min(1.0, float(scenario["fault_value"]) * multiplier))


def _stress_intensity(fault_type: str, profile: str) -> int | float:
    if fault_type == "error":
        return 1.0 if profile in {"intermittent", "burst", "ramp"} else 0.8
    return {"step_early": 500, "step_late": 500, "ramp": 600, "intermittent": 600, "burst": 700}[profile]


def _derived_seed(seed: int, value: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{value}".encode()).digest()[:8], "big")


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=Path("ml/models/m7-lambdamart-v1/model.json"))
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--incidents-per-pair", type=int, default=50)
    parser.add_argument("--healthy-controls", type=int, default=50)
    parser.add_argument("--baseline-requests", type=int, default=100)
    parser.add_argument("--requests-per-incident", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--temporal-repetitions", type=int, default=1)
    parser.add_argument("--stability-scenarios", type=int, default=10)
    parser.add_argument("--stability-repetitions", type=int, default=5)
    args = parser.parse_args()
    configuration = M8AGenerationConfig(
        seed=args.seed,
        incidents_per_pair=args.incidents_per_pair,
        healthy_controls=args.healthy_controls,
        baseline_requests=args.baseline_requests,
        requests_per_incident=args.requests_per_incident,
        concurrency=args.concurrency,
        temporal_repetitions=args.temporal_repetitions,
        stability_scenarios=args.stability_scenarios,
        stability_repetitions=args.stability_repetitions,
    )
    print(
        json.dumps(
            generate(args.output_dir, BenchmarkTopology.load(args.topology), configuration, args.model),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
