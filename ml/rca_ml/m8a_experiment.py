"""Compose frozen zero-shot and cross-system M8A evaluation artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .dataset import read_jsonl, sha256_file
from .m8a_evaluate import (
    evaluate_topology,
    feature_distribution_shift,
    load_dataset,
    system_holdout_matrix,
)
from .m8a_report import render_false_positives, render_results
from .schema import FEATURE_COLUMNS, MODEL_VERSION
from .train import load_model, save_json

M8A_MODEL_VERSION = "m8a-lambdamart-cross-v1"


def run(args: argparse.Namespace) -> dict:
    model_path = args.m7_model
    m7_manifest = json.loads((model_path.parent / "training_manifest.json").read_text(encoding="utf-8"))
    if m7_manifest["model_version"] != MODEL_VERSION or m7_manifest["model_sha256"] != sha256_file(model_path):
        raise ValueError("M7 frozen model does not match its training manifest")
    frozen = load_model(model_path)
    evaluations = {
        "B": evaluate_topology(args.topology_b_dataset, frozen, seed=args.seed + 1),
        "C": evaluate_topology(args.topology_c_dataset, frozen, seed=args.seed + 2),
    }
    b_features, b_labels, b_manifest = load_dataset(args.topology_b_dataset)
    c_features, c_labels, c_manifest = load_dataset(args.topology_c_dataset)
    a_features = read_jsonl(args.topology_a_dataset / "features.jsonl")
    a_labels = read_jsonl(args.topology_a_dataset / "labels.jsonl")
    b_zero_ids = {label["incident_id"] for label in b_labels if label["experiment_kind"] == "zero_shot"}
    c_zero_ids = {label["incident_id"] for label in c_labels if label["experiment_kind"] == "zero_shot"}
    datasets = {
        "A": (a_features, a_labels),
        "B": ([value for value in b_features if value["incident_id"] in b_zero_ids], [value for value in b_labels if value["incident_id"] in b_zero_ids]),
        "C": ([value for value in c_features if value["incident_id"] in c_zero_ids], [value for value in c_labels if value["incident_id"] in c_zero_ids]),
    }
    model_dir = args.model_dir
    holdouts = system_holdout_matrix(
        datasets,
        model_path,
        model_dir,
        selected_parameters=m7_manifest["hyperparameters"],
        rounds=m7_manifest["training_rounds"],
        seed=args.seed,
    )
    shift = feature_distribution_shift(datasets)
    verdicts = _verdicts(evaluations)
    result = {
        "experiment_version": "m8a-v1",
        "model_family": M8A_MODEL_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "frozen_m7_model": {
            "version": MODEL_VERSION,
            "sha256": m7_manifest["model_sha256"],
            "feature_columns": FEATURE_COLUMNS,
        },
        "zero_shot": evaluations,
        "system_holdout": holdouts,
        "feature_distribution_shift": shift,
        "verdicts": verdicts,
    }
    save_json(model_dir / "evaluation.json", result)
    save_json(
        model_dir / "training_manifest.json",
        {
            "model_version": M8A_MODEL_VERSION,
            "source_model": MODEL_VERSION,
            "source_model_sha256": m7_manifest["model_sha256"],
            "feature_schema": m7_manifest["ml_feature_schema"],
            "feature_columns": FEATURE_COLUMNS,
            "hyperparameters": m7_manifest["hyperparameters"],
            "training_rounds": m7_manifest["training_rounds"],
            "random_seed": args.seed,
            "dataset_runs": {"B": b_manifest["run_id"], "C": c_manifest["run_id"]},
            "holdout_models": {system: value["model_sha256"] for system, value in holdouts.items()},
        },
    )
    render_results(
        args.report,
        m7_manifest=m7_manifest,
        manifests={"B": b_manifest, "C": c_manifest},
        zero_shot=evaluations,
        system_holdout=holdouts,
        feature_shift=shift,
        verdicts=verdicts,
    )
    render_false_positives(args.false_positive_report, evaluations)
    print(json.dumps({"verdicts": verdicts, "zero_shot": evaluations, "system_holdout": holdouts}, indent=2, sort_keys=True))
    return result


def _verdicts(evaluations: dict[str, dict]) -> dict:
    statuses = [evaluations[system]["transfer_status"] for system in ("B", "C")]
    if statuses == ["STRONG_TRANSFER", "STRONG_TRANSFER"]:
        learned = "STRONG_TRANSFER"
    elif "FAILED_TRANSFER" not in statuses:
        learned = "PARTIAL_TRANSFER"
    else:
        learned = "FAILED_TRANSFER"
    feature_success = []
    for system in ("B", "C"):
        metrics = evaluations[system]["conditional_nontrivial_metrics"]
        feature_success.append(max(metrics["hybrid_v1"]["ac_at_1"], metrics["topology_consistency"]["ac_at_1"]) - metrics["chance"]["ac_at_1"])
    if min(feature_success) >= 0.20:
        representation = "TRANSFERABLE"
    elif max(feature_success) >= 0.10:
        representation = "PARTIALLY_TRANSFERABLE"
    else:
        representation = "NOT_TRANSFERABLE"
    return {
        "feature_representation": representation,
        "m7_lambdamart": learned,
        "rationale": (
            "Verdicts separate representation quality from the frozen learned ranker. They use conditional performance above chance, "
            "end-to-end detection-limited quality, paired comparisons and survival on both unseen graph structures; they are not claims of external-domain transfer."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology-a-dataset", type=Path, required=True)
    parser.add_argument("--topology-b-dataset", type=Path, required=True)
    parser.add_argument("--topology-c-dataset", type=Path, required=True)
    parser.add_argument("--m7-model", type=Path, default=Path("ml/models/m7-lambdamart-v1/model.json"))
    parser.add_argument("--model-dir", type=Path, default=Path("ml/models/m8a-lambdamart-cross-v1"))
    parser.add_argument("--report", type=Path, default=Path("docs/m8a-results.md"))
    parser.add_argument("--false-positive-report", type=Path, default=Path("docs/m8a-false-positives.md"))
    parser.add_argument("--seed", type=int, default=20260904)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
