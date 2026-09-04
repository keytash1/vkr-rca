"""Deterministic synthetic temporal corpus and detector-v2 selection."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import asdict

import numpy as np

from .detector_v2 import Config, config_grid, detect_operation, error_z, robust_residuals

PROFILES = ("healthy", "constant", "step_early", "step_late", "ramp", "intermittent", "burst")
TOPOLOGIES = ("A", "B", "C")


def corpus(seed: int = 20260904) -> list[dict]:
    records = []
    for topology_index, topology in enumerate(TOPOLOGIES):
        for profile_index, profile in enumerate(PROFILES):
            for scenario in range(6):
                for repeat in range(5):
                    scenario_id = f"{topology}-{profile}-{scenario}"
                    split = "validation" if int(hashlib.sha256(scenario_id.encode()).hexdigest(), 16) % 5 >= 3 else "development"
                    random = np.random.default_rng(seed + topology_index * 100_000 + profile_index * 10_000 + scenario * 100 + repeat)
                    baseline = np.maximum(0.01, random.lognormal(mean=2.3, sigma=0.08, size=200))
                    current = np.maximum(0.01, random.lognormal(mean=2.3, sigma=0.08, size=60))
                    current = _inject(current, profile, scenario)
                    records.append({
                        "incident_id": f"{scenario_id}-r{repeat}", "scenario_id": scenario_id, "topology": topology,
                        "profile": profile, "repeat": repeat, "split": split, "is_fault": profile != "healthy",
                        "baseline_latency_ms": baseline.tolist(), "current_latency_ms": current.tolist(),
                        "baseline_failed": [False] * len(baseline), "current_failed": [False] * len(current),
                    })
    return records


def select_config(records: list[dict]) -> dict:
    validation = [record for record in records if record["split"] == "validation"]
    candidates = []
    for config in config_grid():
        metrics = evaluate(records=validation, config=config)
        candidates.append({"config": config, "metrics": metrics})
    passing = [value for value in candidates if value["metrics"]["healthy_fpr"] <= 0.10]
    if not passing:
        raise ValueError("no temporal configuration satisfies synthetic FPR constraint")
    passing.sort(key=lambda value: (-value["metrics"]["recall"], value["metrics"]["healthy_fpr"], _complexity(value["config"]), value["config"].digest()))
    selected = passing[0]
    variants = {}
    for variant in ("multiscale_location", "multiscale_location_tail", "cusum", "combined_temporal_v2"):
        family = [value for value in candidates if value["config"].variant == variant]
        family.sort(key=lambda value: (-value["metrics"]["recall"], value["metrics"]["healthy_fpr"], value["config"].digest()))
        best = family[0]
        variants[variant] = {"config": asdict(best["config"]), "config_sha256": best["config"].digest(),
                             "metrics": best["metrics"]}
    return {
        "selected_config": selected["config"],
        "selected_metrics": selected["metrics"],
        "candidate_count": len(candidates),
        "fpr_passing_count": len(passing),
        "selection_order": "higher validation recall, lower FPR, simpler variant/config, config hash",
        "variant_validation": variants,
        "split_counts": dict(Counter(record["split"] for record in records)),
        "scenario_overlap": sorted({r["scenario_id"] for r in records if r["split"] == "development"} &
                                   {r["scenario_id"] for r in records if r["split"] == "validation"}),
    }


def evaluate(records: list[dict], config: Config) -> dict:
    rows = []
    for record in records:
        result = detect_operation(record["baseline_latency_ms"], record["current_latency_ms"],
                                  record["baseline_failed"], record["current_failed"], config)
        rows.append({**record, "detected": result["anomalous"], "result": result})
    faults = [row for row in rows if row["is_fault"]]
    healthy = [row for row in rows if not row["is_fault"]]
    by_profile = {}
    for profile in PROFILES:
        selected = [row for row in rows if row["profile"] == profile]
        by_profile[profile] = sum(row["detected"] for row in selected) / max(1, len(selected))
    by_topology = {}
    for topology in TOPOLOGIES:
        selected = [row for row in rows if row["topology"] == topology]
        topology_faults = [row for row in selected if row["is_fault"]]
        topology_healthy = [row for row in selected if not row["is_fault"]]
        by_topology[topology] = {
            "recall": sum(row["detected"] for row in topology_faults) / max(1, len(topology_faults)),
            "healthy_fpr": sum(row["detected"] for row in topology_healthy) / max(1, len(topology_healthy)),
        }
    consistency = []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["scenario_id"]].append(row["detected"])
    for scenario, values in sorted(grouped.items()):
        consistency.append({"scenario_id": scenario, "detection_rate": sum(values) / len(values)})
    return {
        "cases": len(rows), "faults": len(faults), "healthy": len(healthy),
        "recall": sum(row["detected"] for row in faults) / max(1, len(faults)),
        "healthy_fpr": sum(row["detected"] for row in healthy) / max(1, len(healthy)),
        "by_profile": by_profile, "by_topology": by_topology,
        "repeatability": {
            "mean_detection_rate": float(np.mean([value["detection_rate"] for value in consistency])),
            "variance": float(np.var([value["detection_rate"] for value in consistency])),
            "inconsistent_scenarios": sum(0 < value["detection_rate"] < 1 for value in consistency),
        },
    }


def v1_evaluate(records: list[dict]) -> dict:
    converted = []
    for record in records:
        residuals, _ = robust_residuals(record["baseline_latency_ms"], record["current_latency_ms"])
        location = float(np.median(residuals[-20:])) if len(residuals) >= 20 else 0.0
        errors = error_z(record["baseline_failed"], record["current_failed"][-20:])
        converted.append({**record, "detected": location >= 3.5 or (errors is not None and errors >= 3.0)})
    return _summarize(converted)


def _summarize(rows: list[dict]) -> dict:
    faults = [row for row in rows if row["is_fault"]]
    healthy = [row for row in rows if not row["is_fault"]]
    by_profile = {profile: sum(row["detected"] for row in rows if row["profile"] == profile) /
                  max(1, sum(row["profile"] == profile for row in rows)) for profile in PROFILES}
    by_topology = {}
    for topology in TOPOLOGIES:
        selected = [row for row in rows if row["topology"] == topology]
        tf = [row for row in selected if row["is_fault"]]; th = [row for row in selected if not row["is_fault"]]
        by_topology[topology] = {"recall": sum(row["detected"] for row in tf) / max(1, len(tf)),
                                 "healthy_fpr": sum(row["detected"] for row in th) / max(1, len(th))}
    grouped = defaultdict(list)
    for row in rows: grouped[row["scenario_id"]].append(row["detected"])
    rates = [sum(values) / len(values) for values in grouped.values()]
    return {"cases": len(rows), "faults": len(faults), "healthy": len(healthy),
            "recall": sum(row["detected"] for row in faults) / max(1, len(faults)),
            "healthy_fpr": sum(row["detected"] for row in healthy) / max(1, len(healthy)),
            "by_profile": by_profile, "by_topology": by_topology,
            "repeatability": {"mean_detection_rate": float(np.mean(rates)), "variance": float(np.var(rates)),
                              "inconsistent_scenarios": sum(0 < value < 1 for value in rates)}}


def config_json(config: Config) -> dict:
    return {"detector_version": "detector-v2", "feature_schema_version": "m9a-temporal-v1",
            "config": asdict(config), "config_sha256": config.digest()}


def _inject(values: np.ndarray, profile: str, scenario: int) -> np.ndarray:
    result = values.copy()
    strength = 0.65 + 0.08 * scenario
    if profile == "constant":
        result *= np.exp(strength)
    elif profile == "step_early":
        result[5:] *= np.exp(strength)
    elif profile == "step_late":
        result[-10:] *= np.exp(strength + 0.25)
    elif profile == "ramp":
        result *= np.exp(np.linspace(0, strength + 0.2, len(result)))
    elif profile == "intermittent":
        result[::3] *= np.exp(strength + 0.45)
    elif profile == "burst":
        start = 8 + scenario * 6
        result[start : start + 5] *= np.exp(strength + 0.8)
    return result


def _complexity(config: Config) -> tuple:
    order = {"multiscale_location": 0, "cusum": 1, "multiscale_location_tail": 2, "combined_temporal_v2": 3}
    return (order[config.variant], len(config.windows), config.tail_quantile, config.cusum_k,
            config.location_threshold, config.tail_threshold, config.cusum_threshold)
