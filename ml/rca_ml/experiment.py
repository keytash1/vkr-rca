"""End-to-end M7 generation, training, evaluation, artifact and report pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path

import numpy
import scipy
import xgboost

from .dataset import (
    build_candidate_rows,
    enrich_labels,
    read_jsonl,
    sha256_file,
    write_jsonl,
)
from .evaluate import evaluate_experiment
from .generate import GenerationConfig, RCAClient, generate
from .live import run_live_scenarios
from .report import render_report
from .schema import (
    FEATURE_COLUMNS,
    FEATURE_GROUPS,
    FEATURE_SCHEMA_VERSION,
    MODEL_VERSION,
    SOURCE_FEATURE_SCHEMA_VERSION,
)
from .split import duplicate_fingerprints_across_splits, stratified_split
from .train import load_model, save_json, select_and_train


def run(args: argparse.Namespace) -> dict:
    repository = Path(__file__).resolve().parents[2]
    run_id = args.run_id or dt.datetime.now(dt.UTC).strftime("m7-%Y%m%dT%H%M%SZ")
    dataset_dir = args.dataset_dir or repository / "artifacts" / "m7" / run_id
    client = RCAClient(args.gateway_url, args.orders_url, args.payment_url, args.rca_url)
    config = GenerationConfig(
        seed=args.seed,
        incidents_per_pair=args.incidents_per_pair,
        healthy_controls=args.healthy_controls,
        baseline_requests=args.baseline_requests,
        requests_per_incident=args.requests_per_incident,
        concurrency=args.concurrency,
    )
    if args.dataset_dir is None:
        generate(dataset_dir, client, config)
    features_path = dataset_dir / "features.jsonl"
    labels_path = dataset_dir / "labels.jsonl"
    manifest_path = dataset_dir / "manifest.json"
    feature_records = read_jsonl(features_path)
    labels = enrich_labels(feature_records, read_jsonl(labels_path))
    write_jsonl(labels_path, labels)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = dataset_dir.name
    manifest["generation_started_at"] = feature_records[0].get(
        "captured_at", manifest.get("generation_started_at")
    )
    manifest["sha256"]["labels.jsonl"] = sha256_file(labels_path)
    assignments = stratified_split(labels, seed=args.seed)
    duplicates = duplicate_fingerprints_across_splits(labels, assignments)
    if duplicates:
        raise ValueError(f"duplicate scenario fingerprints cross splits: {duplicates}")
    rows = build_candidate_rows(feature_records, labels, assignments)
    candidates_path = dataset_dir / "candidates.jsonl"
    write_jsonl(candidates_path, rows)
    manifest["split_incident_counts"] = dict(sorted(Counter(assignments.values()).items()))
    manifest["exact_duplicate_fingerprints_across_splits"] = 0
    manifest["sha256"]["candidates.jsonl"] = sha256_file(candidates_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    labels_by_id = {label["incident_id"]: label for label in labels}
    model_dir = args.model_dir or repository / "ml" / "models" / MODEL_VERSION
    model_path = model_dir / "model.json"
    training = select_and_train(rows, labels_by_id, assignments, model_path, seed=args.seed)
    model = load_model(model_path)
    evaluation = evaluate_experiment(
        feature_records,
        labels,
        rows,
        assignments,
        model,
        selected_parameters=training["selected_hyperparameters"],
        rounds=training["training_rounds"],
        seed=args.seed,
    )
    live_results = run_live_scenarios(model, client, config) if args.live else []
    results = {"training": training, "evaluation": evaluation, "live_results": live_results}
    save_json(dataset_dir / "results.json", results)
    save_json(model_dir / "validation_search.json", training["search"])
    save_json(model_dir / "evaluation.json", evaluation)
    save_json(model_dir / "live_evaluation.json", live_results)
    save_json(
        model_dir / "feature_schema.json",
        {
            "feature_schema": FEATURE_SCHEMA_VERSION,
            "source_feature_schema": SOURCE_FEATURE_SCHEMA_VERSION,
            "feature_columns": FEATURE_COLUMNS,
            "feature_groups": FEATURE_GROUPS,
        },
    )
    combined_dataset_sha = hashlib.sha256(
        (manifest["sha256"]["features.jsonl"] + manifest["sha256"]["labels.jsonl"]).encode()
    ).hexdigest()
    split_counts = Counter(assignments.values())
    training_manifest = {
        "model_version": MODEL_VERSION,
        "ml_feature_schema": FEATURE_SCHEMA_VERSION,
        "source_m6_schema": SOURCE_FEATURE_SCHEMA_VERSION,
        "git_commit_used_for_dataset": manifest["git_commit"],
        "dataset_run_id": manifest["run_id"],
        "dataset_sha256": combined_dataset_sha,
        "dataset_file_sha256": manifest["sha256"],
        "train_validation_test_incident_counts": dict(sorted(split_counts.items())),
        "random_seeds": {"dataset": args.seed, "split": args.seed, "xgboost": args.seed},
        "python_version": platform.python_version(),
        "xgboost_version": xgboost.__version__,
        "numpy_version": numpy.__version__,
        "scipy_version": scipy.__version__,
        "feature_columns": FEATURE_COLUMNS,
        "hyperparameters": training["selected_hyperparameters"],
        "objective": "rank:ndcg",
        "tree_method": "hist",
        "lambdarank_pair_method": "topk",
        "lambdarank_num_pair_per_sample": 3,
        "best_iteration": training["best_iteration"],
        "training_rounds": training["training_rounds"],
        "training_timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "model_sha256": sha256_file(model_path),
    }
    save_json(model_dir / "training_manifest.json", training_manifest)
    render_report(
        args.report or repository / "docs" / "m7-results.md",
        dataset_manifest=manifest,
        labels=labels,
        assignments=assignments,
        training=training,
        evaluation=evaluation,
        live_results=live_results,
    )
    print(
        json.dumps(
            {
                "dataset_dir": str(dataset_dir),
                "selected_hyperparameters": training["selected_hyperparameters"],
                "best_iteration": training["best_iteration"],
                "counts": evaluation["counts"],
                "detection": evaluation["detection"],
                "test_nontrivial_metrics": evaluation["test_nontrivial_metrics"],
                "end_to_end_ac_at_1": evaluation["end_to_end_ac_at_1"],
                "label_permutation": evaluation["label_permutation"],
                "root_holdout": evaluation["root_holdout"],
                "live_truth_ranks": {
                    result["scenario"]: result["truth_rank"] for result in live_results
                },
                "learned_model_candidate_status": evaluation["learned_model_candidate_status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--dataset-dir", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--incidents-per-pair", type=int, default=100)
    parser.add_argument("--healthy-controls", type=int, default=60)
    parser.add_argument("--baseline-requests", type=int, default=100)
    parser.add_argument("--requests-per-incident", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--gateway-url", default="http://localhost:18080")
    parser.add_argument("--orders-url", default="http://localhost:8081")
    parser.add_argument("--payment-url", default="http://localhost:8082")
    parser.add_argument("--rca-url", default="http://localhost:18090")
    parser.add_argument("--live", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
