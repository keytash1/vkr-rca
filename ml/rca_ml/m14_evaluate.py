"""One-time scoring and truth opening for the final locked M14 transfer test."""

from __future__ import annotations

import argparse
import json
import math
import resource
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .dataset import sha256_file
from .m13_protocol import paired_bootstrap, ranking_metrics, truth_rank
from .m14_runtime import FrozenM13TransferRuntime

MODELS = ("chance", "metric_heuristic", "frozen_m11", "frozen_m13")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _verify_freeze(root: Path) -> tuple[dict, Path]:
    model_dir = root / "ml/models/m14"; freeze = json.loads((model_dir / "freeze-manifest.json").read_text())
    checks = {
        root / "deploy/m14/config.json": freeze["config_sha256"],
        root / "docs/m14-protocol.md": freeze["protocol_sha256"],
        model_dir / "incident-plan.json": freeze["incident_plan_sha256"],
        model_dir / "healthy-baseline.json": freeze["healthy_baseline_sha256"],
        model_dir / "legacy-metric-baseline.json": freeze["legacy_baseline_sha256"],
        model_dir / "frozen-inputs.json": freeze["frozen_inputs_sha256"],
    }
    for path, expected in checks.items():
        if sha256_file(path) != expected: raise RuntimeError(f"M14 frozen artifact drift: {path.relative_to(root)}")
    frozen_inputs = json.loads((model_dir / "frozen-inputs.json").read_text())
    verify_frozen_inputs(root, frozen_inputs)
    run_dir = root / "external-data/m14/runs/locked-v1"
    if sha256_file(run_dir / "healthy/baseline.json") != freeze["healthy_raw_sha256"]:
        raise RuntimeError("M14 healthy telemetry seal mismatch")
    index_path = run_dir / "locked/telemetry-index.jsonl"
    if sha256_file(index_path) != freeze["telemetry_index_sha256"]: raise RuntimeError("M14 telemetry index seal mismatch")
    for item in _load_jsonl(index_path):
        if sha256_file(run_dir / item["telemetry_path"]) != freeze["telemetry_sha256"][item["incident_id"]]: raise RuntimeError(f"M14 telemetry seal mismatch: {item['incident_id']}")
    return freeze, run_dir


def verify_frozen_inputs(root: Path, frozen_inputs: dict) -> None:
    if not frozen_inputs.get("files"):
        raise RuntimeError("M14 frozen dependency inventory is missing")
    for name, expected in frozen_inputs["files"].items():
        path = root / name
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"M14 frozen dependency drift: {name}")


def score(root: Path) -> dict:
    freeze, run_dir = _verify_freeze(root); model_dir = root / "ml/models/m14"
    predictions_path = run_dir / "locked/sealed-predictions.json"
    if predictions_path.exists() or (model_dir / "scoring-completed.marker").exists(): raise RuntimeError("M14 one-time scoring has already run")
    runtime = FrozenM13TransferRuntime(root); predictions = {name: {} for name in MODELS}; started = time.perf_counter(); latencies = []
    for item in _load_jsonl(run_dir / "locked/telemetry-index.jsonl"):
        payload_path = run_dir / item["telemetry_path"]
        if sha256_file(payload_path) != item["sha256"]: raise RuntimeError("M14 input changed after sealing")
        payload = json.loads(payload_path.read_text()); tick = time.perf_counter(); ranked = runtime.rank_all(payload); latencies.append((time.perf_counter() - tick) * 1000)
        for name in MODELS: predictions[name][item["incident_id"]] = ranked[name]
    predictions_path.write_text(json.dumps(predictions, sort_keys=True, separators=(",", ":")))
    result = {"version": "m14-sealed-predictions-v1", "incidents": len(predictions["frozen_m13"]), "prediction_sha256": sha256_file(predictions_path), "truth_accessed": False, "wall_seconds": time.perf_counter() - started, "latency_ms": {"median": float(np.median(latencies)), "p95": float(np.quantile(latencies, .95)), "max": max(latencies)}}
    (model_dir / "scoring-completed.marker").write_text(json.dumps(result, sort_keys=True) + "\n")
    return result


def _groups(rankings: dict[str, dict[str, list[dict]]], truth: dict[str, dict], field: str) -> dict:
    result = {}
    for value in sorted({item[field] for item in truth.values()}):
        subset = {incident: item for incident, item in truth.items() if item[field] == value}
        result[value] = {name: ranking_metrics({incident: values[incident] for incident in subset}, subset) for name, values in rankings.items()}
    return result


def _macro(groups: dict) -> dict:
    return {model: {metric: float(np.mean([group[model][metric] for group in groups.values()])) for metric in ("candidate_universe_coverage", "ac_at_1", "ac_at_2", "ac_at_3", "ac_at_5", "ac_at_10", "mrr")} for model in MODELS}


def _positive(comparison: dict) -> bool:
    return comparison["ac_at_1"]["cluster"]["supported_positive"] or comparison["mrr"]["cluster"]["supported_positive"]


def decide_verdict(pooled: dict, comparisons: dict, per_fault: dict) -> tuple[str, dict]:
    m13 = pooled["frozen_m13"]
    catastrophic = sum(group["frozen_m13"]["candidate_universe_coverage"] < .9 or group["frozen_m13"]["ac_at_5"] < .5 for group in per_fault.values())
    no_majority = catastrophic < math.ceil(len(per_fault) / 2)
    gates = {
        "coverage_at_least_0_90": m13["candidate_universe_coverage"] >= .9,
        "beats_chance_cluster": _positive(comparisons["chance"]),
        "beats_metric_heuristic_cluster": _positive(comparisons["metric_heuristic"]),
        "beats_frozen_m11_cluster": _positive(comparisons["frozen_m11"]),
        "ac_at_3_at_least_0_80": m13["ac_at_3"] >= .8,
        "ac_at_5_at_least_0_90": m13["ac_at_5"] >= .9,
        "ac_at_5_at_least_0_70": m13["ac_at_5"] >= .7,
        "no_majority_fault_catastrophe": no_majority,
        "catastrophic_fault_families": catastrophic,
    }
    if all(gates[name] for name in ("coverage_at_least_0_90", "beats_chance_cluster", "beats_metric_heuristic_cluster", "beats_frozen_m11_cluster", "ac_at_3_at_least_0_80", "ac_at_5_at_least_0_90", "no_majority_fault_catastrophe")):
        return "STRONG_TRANSFER", gates
    if gates["coverage_at_least_0_90"] and gates["beats_chance_cluster"] and (gates["beats_metric_heuristic_cluster"] or gates["beats_frozen_m11_cluster"]) and gates["ac_at_5_at_least_0_70"] and no_majority:
        return "SUPPORTED_TRANSFER", gates
    if m13["mrr"] > pooled["chance"]["mrr"] and m13["ac_at_5"] >= .5:
        return "LIMITED_TRANSFER", gates
    return "NOT_SUPPORTED", gates


def _bucket(rank: int | None) -> str:
    if rank is None: return "CANDIDATE_UNIVERSE_MISS"
    if rank == 1: return "SUCCESS_AT_1"
    if rank <= 3: return "WITHIN_TOP3_ORDERING_ERROR"
    if rank <= 5: return "WITHIN_TOP5_ORDERING_ERROR"
    if rank <= 10: return "ROOT_BELOW_TOP5"
    return "ROOT_BELOW_TOP10"


def open_results(root: Path) -> dict:
    freeze, run_dir = _verify_freeze(root); model_dir = root / "ml/models/m14"; marker = model_dir / "evaluation-opened.marker"
    if marker.exists() or (model_dir / "evaluation.json").exists(): raise RuntimeError("M14 final truth has already been opened")
    predictions_path = run_dir / "locked/sealed-predictions.json"; score_meta = json.loads((model_dir / "scoring-completed.marker").read_text())
    if sha256_file(predictions_path) != score_meta["prediction_sha256"]: raise RuntimeError("M14 sealed predictions changed")
    truth_path = run_dir / "locked/truth.sealed.jsonl"
    if sha256_file(truth_path) != freeze["locked_truth_sha256"]: raise RuntimeError("M14 truth seal mismatch")
    predictions = json.loads(predictions_path.read_text()); truth_items = _load_jsonl(truth_path); truth = {item["incident_id"]: {**item, "system": "OpenTelemetry-Astronomy-Shop"} for item in truth_items if item["valid_injection"]}
    if len(truth) != 50 or any(set(values) != set(truth) for values in predictions.values()): raise RuntimeError("M14 full denominator mismatch")
    pooled = {name: ranking_metrics(values, truth) for name, values in predictions.items()}
    comparisons = {}
    for baseline in ("chance", "metric_heuristic", "frozen_m11"):
        comparisons[baseline] = {metric: {"incident": paired_bootstrap(predictions["frozen_m13"], predictions[baseline], truth, metric, cluster=False, seed=20260912), "cluster": paired_bootstrap(predictions["frozen_m13"], predictions[baseline], truth, metric, cluster=True, seed=20260912)} for metric in ("ac_at_1", "mrr")}
    per_fault = _groups(predictions, truth, "fault_family"); per_root = _groups(predictions, truth, "root_service"); verdict, gates = decide_verdict(pooled, comparisons, per_fault)
    errors, histogram = [], Counter()
    index_by_id = {item["incident_id"]: item for item in _load_jsonl(run_dir / "locked/telemetry-index.jsonl")}
    for incident, item in sorted(truth.items()):
        rank = truth_rank(predictions["frozen_m13"][incident], item["root_service"]); stage = _bucket(rank); histogram[stage] += 1
        if stage != "SUCCESS_AT_1":
            payload = json.loads((run_dir / index_by_id[incident]["telemetry_path"]).read_text()); flags = ["OOD_DOMAIN_SHIFT"]
            if not payload.get("traces_collected") or not payload.get("traces"): flags.append("MISSING_TRACE_MODALITY")
            if not payload.get("metrics"): flags.append("MISSING_METRIC_MODALITY")
            failures = sum(count for status, count in json.loads(payload["workload_result"]["stdout"])["statuses"].items() if int(status) == 0 or int(status) >= 500)
            if failures > json.loads(payload["workload_result"]["stdout"])["attempts"] / 2: flags.append("LOW_WORKLOAD_SIGNAL")
            errors.append({"incident_id": incident, "root_service": item["root_service"], "fault_family": item["fault_family"], "truth_rank": rank, "primary_stage": stage, "diagnostic_flags": flags})
    result = {
        "version": "m14-final-evaluation-v1", "system": "OpenTelemetry Astronomy Shop", "upstream_commit": freeze["upstream_commit"], "data_role": "USED_TEST", "valid_incidents": len(truth), "clusters": 25,
        "frozen_candidate": "M13 full_candidate_challenger; five-seed LambdaMART; depth=3 eta=0.08 rounds=24", "prediction_sha256": score_meta["prediction_sha256"],
        "pooled": pooled, "paired_m13_vs": comparisons, "per_fault": per_fault, "macro_fault": _macro(per_fault), "per_root": per_root, "macro_root": _macro(per_root),
        "worst_groups": {"fault_ac_at_1": min(((name, values["frozen_m13"]["ac_at_1"]) for name, values in per_fault.items()), key=lambda item: (item[1], item[0])), "root_ac_at_1": min(((name, values["frozen_m13"]["ac_at_1"]) for name, values in per_root.items()), key=lambda item: (item[1], item[0]))},
        "error_analysis": {"histogram": dict(sorted(histogram.items())), "errors": errors}, "verdict": verdict, "verdict_gates": gates,
        "limitations": ["One reserved test system and five represented fault families.", "Diagnostic ranking is not causal proof or calibrated probability.", "Controlled single-host containers are not production deployment evidence.", "No post-test tuning is permitted regardless of outcome."],
        "research_status": "FINAL_RESEARCH_FREEZE", "environment": {"peak_process_ram_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)},
    }
    (model_dir / "evaluation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n"); marker.write_text(json.dumps({"opened": True, "verdict": verdict, "prediction_sha256": score_meta["prediction_sha256"]}, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("score", "open")); parser.add_argument("--root", default="."); args = parser.parse_args(); root = Path(args.root).resolve()
    result = score(root) if args.command == "score" else open_results(root)
    print(json.dumps({"command": args.command, "verdict": result.get("verdict"), "incidents": result.get("valid_incidents", result.get("incidents")), "pooled": result.get("pooled"), "prediction_sha256": result.get("prediction_sha256")}, indent=2, sort_keys=True))


if __name__ == "__main__": main()
