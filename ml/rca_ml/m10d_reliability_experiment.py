"""Locked nested cross-system experiment for M10D-A reliability v2."""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import sha256_file
from .m9b_model import evaluate_model, metrics_for_rankings
from .m10c_experiment import EXTERNAL, RE1, fit_seed, load_rows
from .m10c_integrity import verify_frozen
from .m10c_schema import METRIC_EXPERT_COLUMNS, TRACE_EXPERT_COLUMNS
from .m10c_uncertainty import conformal_quantile
from .m10d_reliability import (
    FEATURE_COLUMNS, SEED, SEEDS, TARGETS, bootstrap_accuracy_delta,
    build_incident_record, calibration_metrics, deterministic_split,
    ensure_truth_free_inference, evaluate_policy, fit_method,
    fit_ood_bounds, fit_policy, policy_accepts, predict_method, serializable_model,
)
from .train import save_json

METHODS = ("margin", "isotonic", "logistic", "monotonic_boosting", "risk_control", "mondrian")
PROBABILITY_METHODS = {"isotonic", "logistic", "monotonic_boosting"}
METHOD_COMPLEXITY = {name: index for index, name in enumerate(METHODS)}
M10C_BASE = "dcf3fd211f10edba5808e3c26a0400ea057d405e"
BASE_WITH_TERMINOLOGY_FIX = "b18c70c4deddb86c637a5fad4c9f68a2ff465423"
EXTERNAL_LABEL = "post-M10C locked evaluation; not pristine external model selection"


def _source(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["incident_id"], row["service"]): row for row in rows}


def _bundle(rows: list[dict], train_ids: list[str], test_ids: list[str], columns: tuple[str, ...], seed: int) -> dict[str, list[dict]]:
    model = fit_seed(rows, train_ids, columns, seed)
    return evaluate_model(model, rows, test_ids, columns)[1]


def ranking_bundle(rows: list[dict], train_ids: list[str], test_ids: list[str], compact: tuple[str, ...], seed: int) -> dict:
    return {
        "core": _bundle(rows, train_ids, test_ids, compact, seed),
        "metric": _bundle(rows, train_ids, test_ids, METRIC_EXPERT_COLUMNS, seed),
        "trace": _bundle(rows, train_ids, test_ids, TRACE_EXPERT_COLUMNS, seed),
    }


def oof_bundle(rows: list[dict], ids: dict[str, list[str]], systems: tuple[str, ...], compact: tuple[str, ...], seed: int) -> dict:
    combined = {"core": {}, "metric": {}, "trace": {}}
    provenance = {}
    for held_out in systems:
        training = sum((ids[name] for name in systems if name != held_out), [])
        if not training:
            raise ValueError("nested OOF ranker needs at least two systems")
        result = ranking_bundle(rows, training, ids[held_out], compact, seed)
        for name in combined:
            combined[name].update(result[name])
        for incident in ids[held_out]:
            provenance[incident] = set(training)
    if any(incident in training for incident, training in provenance.items()):
        raise ValueError("OOF ranker leaked its held-out incident")
    return combined


def records_from_bundle(bundle: dict, source: dict, bounds: dict, quantile: float, include_target: bool = True) -> list[dict]:
    return [
        build_incident_record(
            incident, bundle["core"][incident], source, bounds, quantile,
            bundle["metric"].get(incident), bundle["trace"].get(incident), include_target,
        )
        for incident in sorted(bundle["core"])
    ]


def _subset(records: list[dict], ids: list[str]) -> list[dict]:
    wanted = set(ids)
    return [record for record in records if record["incident_id"] in wanted]


def _safe_mean(values: list[float | None]) -> float:
    return float(np.mean([0.0 if value is None else value for value in values]))


def nested_development(rows: list[dict], ids: dict[str, list[str]], compact: tuple[str, ...]) -> dict:
    source = _source(rows)
    folds = []
    started = time.perf_counter()
    for seed in SEEDS:
        for held_out in RE1:
            inner_systems = tuple(system for system in RE1 if system != held_out)
            inner_ids = sum((ids[name] for name in inner_systems), [])
            outer_bundle = ranking_bundle(rows, inner_ids, ids[held_out], compact, seed)
            inner_oof = oof_bundle(rows, ids, inner_systems, compact, seed)
            quantile = conformal_quantile(inner_oof["core"], 0.90)
            bounds = fit_ood_bounds(rows, inner_ids)
            train_records = records_from_bundle(inner_oof, source, bounds, quantile)
            held_records = records_from_bundle(outer_bundle, source, bounds, quantile)
            fit_ids, calibration_ids = deterministic_split(
                [record["incident_id"] for record in train_records], f"m10d:{seed}:{held_out}"
            )
            fit_records = _subset(train_records, fit_ids)
            calibration_records = _subset(train_records, calibration_ids)
            method_results = {}
            for method in METHODS:
                fitted = fit_method(method, fit_records, seed)
                held_scores = predict_method(method, fitted, held_records)
                policies = {}
                for target in TARGETS:
                    policy = fit_policy(method, fitted, calibration_records, target, fit_records)
                    held_out_metrics = evaluate_policy(held_records, held_scores, policy)
                    # Per-fold curves are redundant and make the versioned artifact
                    # enormous; AURC is retained here and complete locked-external
                    # curves are persisted below.
                    held_out_metrics.pop("risk_coverage_curve")
                    policies[str(target)] = {
                        "calibration": {key: value for key, value in policy.items() if key not in {"regime_thresholds"}},
                        "held_out": held_out_metrics,
                    }
                result = {"policies": policies}
                if method in PROBABILITY_METHODS:
                    result["correctness_calibration"] = calibration_metrics(held_records, held_scores)
                method_results[method] = result
            folds.append({
                "seed": seed, "held_out": held_out, "fit_incidents": len(fit_records),
                "calibration_incidents": len(calibration_records), "held_out_incidents": len(held_records),
                "conformal_quantile_90": quantile, "methods": method_results,
            })
    summary = {}
    for method in METHODS:
        method_folds = [fold["methods"][method] for fold in folds]
        result = {}
        for target in TARGETS:
            values = [value["policies"][str(target)]["held_out"] for value in method_folds]
            accuracies = [value["selective_ac_at_1"] for value in values]
            coverages = [value["coverage"] for value in values]
            by_system = {}
            for system in RE1:
                system_values = [fold["methods"][method]["policies"][str(target)]["held_out"] for fold in folds if fold["held_out"] == system]
                by_system[system] = {
                    "selective_ac_at_1_mean": _safe_mean([value["selective_ac_at_1"] for value in system_values]),
                    "coverage_mean": float(np.mean([value["coverage"] for value in system_values])),
                }
            result[str(target)] = {
                "selective_ac_at_1": seed_stats(accuracies),
                "coverage": seed_stats(coverages),
                "aurc": seed_stats([value["aurc"] for value in values]),
                "by_held_out_system": by_system,
            }
        if method in PROBABILITY_METHODS:
            result["correctness_calibration"] = {
                "brier": seed_stats([value["correctness_calibration"]["brier"] for value in method_folds]),
                "ece": seed_stats([value["correctness_calibration"]["ece"] for value in method_folds]),
            }
        summary[method] = result
    selected, selection = select_method(summary)
    return {"folds": folds, "summary": summary, "selected_method": selected,
            "selection": selection, "runtime_seconds": time.perf_counter() - started}


def seed_stats(values: list[float | None]) -> dict:
    numeric = [0.0 if value is None else float(value) for value in values]
    return {"mean": float(np.mean(numeric)), "std": float(np.std(numeric)),
            "min": min(numeric), "max": max(numeric), "observations": len(numeric)}


def select_method(summary: dict) -> tuple[str, dict]:
    candidates = []
    for method, value in summary.items():
        policy = value["0.9"]
        accuracy = policy["selective_ac_at_1"]["mean"]
        coverage = policy["coverage"]["mean"]
        minimum_system = min(item["selective_ac_at_1_mean"] for item in policy["by_held_out_system"].values())
        passes = accuracy >= 0.90 and coverage >= 0.50 and minimum_system >= 0.80
        candidates.append({"method": method, "passes": passes, "mean_accuracy": accuracy,
                           "mean_coverage": coverage, "minimum_system_accuracy": minimum_system,
                           "mean_aurc": policy["aurc"]["mean"]})
    eligible = [item for item in candidates if item["passes"]]
    if eligible:
        selected = sorted(eligible, key=lambda item: (-item["mean_coverage"], -item["mean_accuracy"], item["mean_aurc"], METHOD_COMPLEXITY[item["method"]]))[0]
        rule = "largest mean coverage among methods passing all preregistered development gates"
    else:
        selected = sorted(candidates, key=lambda item: (-item["mean_accuracy"], -item["mean_coverage"], item["mean_aurc"], METHOD_COMPLEXITY[item["method"]]))[0]
        rule = "no method passed; freeze highest mean accuracy, then coverage, AURC and lower complexity"
    return selected["method"], {"rule": rule, "candidates": candidates, "selected": selected,
                                "external_360_consulted": False}


def frozen_external_bundle(rows: list[dict], test_ids: list[str], root: Path, compact: tuple[str, ...]) -> tuple[dict, float]:
    models = {}
    for name, filename in (("core", "m10c-core-v2.json"), ("metric", "metric-expert.json"), ("trace", "trace-topology-expert.json")):
        model = xgb.Booster(); model.load_model(root / "ml/models/m10c-v2" / filename); models[name] = model
    started = time.perf_counter()
    bundle = {
        "core": evaluate_model(models["core"], rows, test_ids, compact)[1],
        "metric": evaluate_model(models["metric"], rows, test_ids, METRIC_EXPERT_COLUMNS)[1],
        "trace": evaluate_model(models["trace"], rows, test_ids, TRACE_EXPERT_COLUMNS)[1],
    }
    return bundle, time.perf_counter() - started


def freeze_and_external(root: Path, rows: list[dict], ids: dict[str, list[str]], cases: list[dict], compact: tuple[str, ...],
                        method: str, development_passes: bool, model_dir: Path) -> dict:
    source = _source(rows)
    all_re1 = sum((ids[name] for name in RE1), [])
    oof = oof_bundle(rows, ids, RE1, compact, SEED)
    frozen_m10c = json.loads((root / "ml/models/m10c-v2/evaluation.json").read_text())
    quantile = float(frozen_m10c["uncertainty"]["conformal"]["0.9"]["quantile"])
    bounds = fit_ood_bounds(rows, all_re1)
    development_records = records_from_bundle(oof, source, bounds, quantile)
    fit_ids, calibration_ids = deterministic_split([record["incident_id"] for record in development_records], "m10d-final-freeze")
    fit_records = _subset(development_records, fit_ids)
    calibration_records = _subset(development_records, calibration_ids)
    fitted = fit_method(method, fit_records, SEED)
    policies = {str(target): fit_policy(method, fitted, calibration_records, target, fit_records) for target in TARGETS}

    external_ids = sum((ids[name] for name in EXTERNAL), [])
    external_bundle, rank_seconds = frozen_external_bundle(rows, external_ids, root, compact)
    external_records = records_from_bundle(external_bundle, source, bounds, quantile)
    reliability_started = time.perf_counter()
    external_scores = predict_method(method, fitted, external_records)
    reliability_seconds = time.perf_counter() - reliability_started
    policy_results = {str(target): evaluate_policy(external_records, external_scores, policy) for target, policy in ((target, policies[str(target)]) for target in TARGETS)}
    margin_scores = predict_method("margin", None, external_records)
    bootstrap = bootstrap_accuracy_delta(external_records, external_scores, margin_scores,
                                         policy_results["0.9"]["coverage"])

    metadata = {case["incident_id"]: case for case in cases}
    breakdown = {}
    for dataset in EXTERNAL:
        selected = [index for index, record in enumerate(external_records) if metadata[record["incident_id"]]["dataset"] == dataset]
        breakdown[dataset] = evaluate_policy([external_records[index] for index in selected], [external_scores[index] for index in selected], policies["0.9"])
    by_system = {}
    system_labels = {"ob": "Online Boutique", "ss": "Sock Shop", "tt": "Train Ticket"}
    for system in ("ob", "ss", "tt"):
        selected = [index for index, record in enumerate(external_records) if metadata[record["incident_id"]]["system"] == system]
        by_system[system_labels[system]] = evaluate_policy(
            [external_records[index] for index in selected],
            [external_scores[index] for index in selected], policies["0.9"],
        )
    external_gate = policy_results["0.9"]["selective_ac_at_1"] is not None and policy_results["0.9"]["selective_ac_at_1"] >= 0.90 and policy_results["0.9"]["coverage"] >= 0.50
    verdict = "PROMOTED" if development_passes and external_gate else "REJECTED"

    model_dir.mkdir(parents=True, exist_ok=True)
    save_json(model_dir / "frozen-policy.json", {
        "version": "m10d-reliability-v2", "method": method, "feature_columns": list(FEATURE_COLUMNS),
        "model": serializable_model(method, fitted), "policies": policies,
        "fit_incidents": len(fit_records), "calibration_incidents": len(calibration_records),
        "ood_bounds": bounds,
        "external_evaluation_locked_after_this_file": True, "m10c_conformal_quantile_90_unchanged": quantile,
    })
    if hasattr(fitted, "booster"):
        fitted.booster.save_model(model_dir / "reliability-booster.json")

    margin_median = float(np.median([record["features"]["margin_top1_top2"] for record in development_records]))
    wrong = [record for record in external_records if not record["top1_correct"]]
    accepted_wrong = [record for record, score in zip(external_records, external_scores, strict=True)
                      if not record["top1_correct"] and policy_accepts(policies["0.9"], record, score)]
    taxonomy = {
        "ranking_error": len(wrong),
        "confidence_error": len(accepted_wrong),
        "metric_ambiguity": sum(record["features"]["metric_coverage"] < 0.5 for record in wrong),
        "missing_modality": sum(min(record["features"][name] for name in ("metrics_present", "traces_present", "topology_present")) < 1 for record in wrong),
        "candidate_ambiguity": sum(record["features"]["margin_top1_top2"] < margin_median for record in wrong),
        "domain_shift": len(wrong),
        "verifier_contradiction_miss": "not applicable to Track A",
        "planner_bad_action": "not applicable to Track A",
    }
    return {
        "verdict": verdict, "method": method, "development_gate": development_passes,
        "external_gate": external_gate, "label": EXTERNAL_LABEL,
        "policies": policy_results, "by_dataset_90": breakdown, "by_system_90": by_system,
        "paired_bootstrap_vs_margin_at_matched_coverage": bootstrap,
        "ranking_metrics": metrics_for_rankings(external_bundle["core"]),
        "correctness_calibration": calibration_metrics(external_records, external_scores) if method in PROBABILITY_METHODS else None,
        "error_taxonomy": taxonomy,
        "performance": {"rank_inference_seconds_total": rank_seconds,
                        "rank_inference_ms_per_incident": 1000 * rank_seconds / len(external_records),
                        "reliability_seconds_total": reliability_seconds,
                        "reliability_ms_per_incident": 1000 * reliability_seconds / len(external_records)},
        "development_table": development_records, "external_table": external_records,
        "external_scores": external_scores.tolist(), "policies_frozen_before_external": True,
    }


def synthetic_compatibility(root: Path) -> dict:
    old_columns = json.loads((root / "ml/models/m8a-lambdamart-cross-v1/training_manifest.json").read_text())["feature_columns"]
    return {
        "status": "NOT_COMPATIBLE_WITH_FROZEN_M10C_INPUT",
        "systems": ["Synthetic-A", "Synthetic-B", "Synthetic-C"],
        "reason": "M8A stores the older M7 candidate representation; it lacks the 32 selected M10C metric/coverage fields and generic metric-service candidate union.",
        "old_feature_count": len(old_columns), "m10c_feature_count": 32,
        "adapter_created": False, "labels_used_to_force_mapping": False,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def run(root: Path, artifact_dir: Path, model_dir: Path) -> dict:
    started = time.perf_counter()
    integrity = verify_frozen(root)
    if not integrity["ok"]:
        raise ValueError(f"frozen M10C inputs changed: {integrity['mismatches']}")
    m10c_eval = json.loads((root / "ml/models/m10c-v2/evaluation.json").read_text())
    compact = tuple(m10c_eval["final_columns"])
    if len(compact) != 32 or m10c_eval["selected_core"] != "compact_stability":
        raise ValueError("M10D-A requires the frozen 32-feature compact stability ranker")
    truth_free = artifact_dir / "truth-free.jsonl"
    cases, rows, ids = load_rows(truth_free, artifact_dir / "truth-free-seal.json", root / "external-data/rcaeval/cases.parquet")
    development = nested_development(rows, ids, compact)
    selected = development["selected_method"]
    selected_gate = development["selection"]["selected"]["passes"]
    locked = freeze_and_external(root, rows, ids, cases, compact, selected, selected_gate, model_dir)

    write_jsonl(model_dir / "reliability-table-development.jsonl", locked.pop("development_table"))
    external_table = locked.pop("external_table")
    external_scores = locked.pop("external_scores")
    external_policy = json.loads((model_dir / "frozen-policy.json").read_text())["policies"]["0.9"]
    deployable = []
    for record, score in zip(external_table, external_scores, strict=True):
        item = ensure_truth_free_inference(record)
        item.update({"reliability_score": score,
                     "decision": "ACCEPT_TOP1" if policy_accepts(external_policy, record, score) else "ABSTAIN_TOP1"})
        deployable.append(item)
    write_jsonl(model_dir / "reliability-table-external-inference.jsonl", deployable)
    write_jsonl(model_dir / "reliability-table-external-evaluation.jsonl", [
        {**record, "reliability_score": score} for record, score in zip(external_table, external_scores, strict=True)
    ])

    model_sizes = {path.name: path.stat().st_size for path in sorted(model_dir.glob("*")) if path.is_file()}
    result = {
        "version": "m10d-reliability-v2", "verdict": locked["verdict"],
        "frozen_base": {"m10c_commit": M10C_BASE, "branch_base": BASE_WITH_TERMINOLOGY_FIX,
                        "selected_ranker": "compact_stability", "features": 32,
                        "integrity": integrity},
        "protocol": {"outer_systems": list(RE1), "seeds": list(SEEDS), "methods": list(METHODS),
                     "targets": list(TARGETS), "bootstrap_resamples": 10_000, "bootstrap_seed": SEED,
                     "identity_features": False, "external_used_for_selection": False},
        "development": development,
        "synthetic_abc": synthetic_compatibility(root),
        "locked_external": locked,
        "m10c_conformal": {"changed": False, "source": "frozen ml/models/m10c-v2/evaluation.json",
                           "result": m10c_eval["uncertainty"]["conformal"]},
        "probability_semantics": "Outputs remain reliability_score, not probability; held-out Brier/ECE are diagnostic only.",
        "model_sizes_bytes": model_sizes,
        "runtime_seconds": time.perf_counter() - started,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "xgboost": xgb.__version__},
    }
    save_json(model_dir / "evaluation.json", result)
    save_json(model_dir / "integrity-manifest.json", {
        "frozen_m10c_model_sha256": sha256_file(root / "ml/models/m10c-v2/m10c-core-v2.json"),
        "frozen_m10c_evaluation_sha256": sha256_file(root / "ml/models/m10c-v2/evaluation.json"),
        "truth_free_sha256": sha256_file(truth_free),
        "artifacts": {path.name: sha256_file(path) for path in sorted(model_dir.glob("*"))
                      if path.is_file() and path.name not in {"evaluation.json", "integrity-manifest.json"}},
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/m10c/m10c-v2"))
    parser.add_argument("--models", type=Path, default=Path("ml/models/m10d-reliability"))
    args = parser.parse_args()
    root = args.root.resolve()
    artifacts = args.artifacts if args.artifacts.is_absolute() else root / args.artifacts
    if not artifacts.exists() and (root / "artifacts/artifacts/m10c/m10c-v2").exists():
        artifacts = root / "artifacts/artifacts/m10c/m10c-v2"
    models = args.models if args.models.is_absolute() else root / args.models
    result = run(root, artifacts, models)
    print(json.dumps({"verdict": result["verdict"], "selected_method": result["development"]["selected_method"],
                      "development_gate": result["development"]["selection"]["selected"]["passes"],
                      "external_90": result["locked_external"]["policies"]["0.9"],
                      "runtime_seconds": result["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
