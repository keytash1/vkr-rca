"""M9B multi-source soft-evidence RCA experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from .dataset import read_jsonl, sha256_file
from .m8b_experiment import BASE_URL, HF_REVISION, INDEX_SHA256, RCAEVAL_REVISION, _download, normalize_root
from .m9b_features import extract_case_features
from .m9b_model import (
    contributions,
    evaluate_model,
    fit_fixed,
    select_hyperparameters,
    truth_ranks,
)
from .m9b_schema import (
    FEATURE_COLUMNS_M9B,
    METRIC_FAMILIES,
    METRIC_MODEL_COLUMNS,
    TOPOLOGY_COLUMNS,
    TRACE_MODEL_COLUMNS,
    validate_schema,
)
from .metrics import paired_bootstrap, rank_metrics
from .train import save_json

SEED = 20260904
EXPERIMENT_VERSION = "m9b-v1"
RE1 = ("RE1-OB", "RE1-SS", "RE1-TT")
METRIC_EXTERNAL = ("RE2-OB", "RE2-SS", "RE2-TT", "RE3-OB", "RE3-SS", "RE3-TT")
MULTISOURCE = ("RE2-OB", "RE2-TT", "RE3-OB", "RE3-TT")
METRIC_SYSTEM_HOLDOUTS = (("OB+SS", ("RE1-OB", "RE1-SS"), "RE1-TT"),
                          ("OB+TT", ("RE1-OB", "RE1-TT"), "RE1-SS"),
                          ("SS+TT", ("RE1-SS", "RE1-TT"), "RE1-OB"))
MULTISOURCE_FOLDS = (("train_RE2-OB_test_TT", "RE2-OB", ("RE2-TT", "RE3-TT")),
                     ("train_RE2-TT_test_OB", "RE2-TT", ("RE2-OB", "RE3-OB")))
M9A_COMMIT = "ace15453ca572905f10e66c03e9cdc2243b05386"
M7_SHA256 = "3728eb0454e46d14265d092d3d17088bc32fe44e8c9cb8d565aa8e934cee7699"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("external-data/rcaeval"))
    parser.add_argument("--m8b-artifacts", type=Path, default=Path("artifacts/m8b/m8b-external-v1"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/m9b/m9b-v1"))
    parser.add_argument("--model-dir", type=Path, default=Path("ml/models/m9b-v1"))
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--official", type=Path, default=Path("artifacts/m9b/m9b-v1/official-baselines.json"))
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        print(json.dumps(smoke(), indent=2, sort_keys=True))
    else:
        run(args)


def smoke() -> dict:
    from .m9b_features import add_incident_percentiles, aggregate_family, channel_features, match_entity

    times = pd.Series(np.arange(0, 1200, dtype=float))
    baseline = np.full(600, 10.0)
    current = np.concatenate((np.full(300, 10.0), np.full(300, 30.0)))
    feature = channel_features(times, pd.Series(np.concatenate((baseline, current))), 600)
    aggregate, explanation = aggregate_family([{**feature, "metric_name": "orders_cpu"}])
    vectors = {"orders": {name: 0.0 for name in FEATURE_COLUMNS_M9B},
               "payment": {name: 0.0 for name in FEATURE_COLUMNS_M9B}}
    vectors["orders"]["metric_cpu_max_shift"] = aggregate["max_shift"]
    add_incident_percentiles(vectors)
    ranking = rank_scores([{"service": service, "score": value["metric_cpu_max_shift"]}
                           for service, value in vectors.items()])
    tiny_rows = []
    for incident in range(8):
        for service, label, score in (("orders", 1, 2.0 + incident / 10), ("payment", 0, .1)):
            row = {name: 0.0 for name in METRIC_MODEL_COLUMNS}
            row.update({"incident_id": f"tiny-{incident}", "service": service, "label": label,
                        "metric_cpu_max_shift": score, "metric_cpu_has": 1.0})
            tiny_rows.append(row)
    tiny_model = fit_fixed(tiny_rows, [f"tiny-{value}" for value in range(6)], METRIC_MODEL_COLUMNS,
                           {"max_depth": 2, "eta": .1, "min_child_weight": 1,
                            "subsample": 1, "colsample_bytree": 1}, 5)
    tiny_metrics, tiny_rankings = evaluate_model(tiny_model, tiny_rows, ["tiny-6", "tiny-7"], METRIC_MODEL_COLUMNS)
    fused = rank_fusion((ranking_with_labels(ranking, "orders"), tiny_rankings["tiny-6"]))
    if ranking[0]["service"] != "orders" or match_entity("orders", ["orders", "payment"]) != "orders":
        raise ValueError("M9B smoke ranking/mapping failed")
    return {"schema": "m9b-v1", "feature_count": len(FEATURE_COLUMNS_M9B),
            "metric_available": feature["available"], "rolling_30_score": feature["rolling_30_score"],
            "winner": explanation["winning_metric"], "ranking": ranking,
            "tiny_model_ac_at_1": tiny_metrics["ac_at_1"], "rank_fusion_winner": fused[0]["service"],
            "label_isolation": "feature builder accepts no root/fault argument"}


def ranking_with_labels(ranking: list[dict], root: str) -> list[dict]:
    return [{**value, "label": int(value["service"] == root)} for value in ranking]


def run(args: argparse.Namespace) -> dict:
    validate_schema()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    args.model_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.data_dir / "cases.parquet"
    if sha256_file(index_path) != INDEX_SHA256:
        raise ValueError("pinned RCAEval index hash mismatch")
    index_generation = pd.read_parquet(index_path, columns=["case", "dataset", "system", "inject_time", "n_metrics", "has_traces"])
    selected = index_generation[index_generation["n_metrics"] > 0].sort_values("case")
    if len(selected) != 735:
        raise ValueError(f"expected 735 metric cases, got {len(selected)}")
    ensure_metric_data(selected, args.data_dir)
    records, seal = generate_truth_free(selected, args)

    # Root/fault labels are loaded only after the persisted feature artifact is sealed.
    labels_index = pd.read_parquet(index_path)
    cases, rows = join_labels(records, labels_index, seal)
    save_json(args.artifact_dir / "labels-and-coverage.json", {"seal": seal, "cases": cases})

    metric_study = metric_models(rows, cases, args.model_dir)
    multisource_study = multisource_models(rows, cases, args.model_dir, args.m8b_artifacts,
                                           metric_study["external"]["rankings"])
    from .m9b_official import run as run_official
    official = run_official(args.data_dir, Path("external-data/RCAEval-source"), labels_index)
    save_json(args.official, official)
    result = {
        "experiment_version": EXPERIMENT_VERSION,
        "source": {"rcaeval_commit": RCAEVAL_REVISION, "hf_revision": HF_REVISION,
                   "index_sha256": INDEX_SHA256},
        "truth_free_seal": seal,
        "coverage": coverage_summary(cases),
        "metric_study": metric_study,
        "multisource_study": multisource_study,
        "official_baselines": official,
    }
    result["verdict"] = verdict(result)
    save_json(args.model_dir / "evaluation.json", _compact(result))
    save_json(args.model_dir / "feature_schema.json", {
        "version": "m9b-v1", "columns": FEATURE_COLUMNS_M9B,
        "metric_model_columns": METRIC_MODEL_COLUMNS,
        "trace_columns": TRACE_MODEL_COLUMNS, "topology_columns": TOPOLOGY_COLUMNS,
    })
    save_json(args.model_dir / "models-manifest.json", models_manifest(result))
    save_json(args.model_dir / "integrity_manifest.json", integrity_manifest(result, args))
    render_reports(result, cases, rows, args.docs, args.model_dir)
    return result


def ensure_metric_data(selected: pd.DataFrame, data_dir: Path) -> None:
    jobs = [(str(row.case), data_dir / str(row.case) / "metrics.parquet")
            for row in selected.itertuples(index=False)
            if not (data_dir / str(row.case) / "metrics.parquet").exists()]
    if not jobs:
        return
    def fetch(job: tuple[str, Path]) -> str:
        case_id, destination = job
        _download(f"{BASE_URL}/{case_id}/metrics.parquet", destination)
        return case_id
    with ThreadPoolExecutor(max_workers=8) as executor:
        for position, case_id in enumerate(executor.map(fetch, jobs), 1):
            if position % 25 == 0 or position == len(jobs):
                print(f"m9b metrics {position}/{len(jobs)} {case_id}", flush=True)


def generate_truth_free(selected: pd.DataFrame, args: argparse.Namespace) -> tuple[list[dict], dict]:
    path = args.artifact_dir / "truth-free.jsonl"
    existing = read_jsonl(path) if path.exists() else []
    done = {record["external_case_id"] for record in existing}
    m8b = {record["external_case_id"]: record for record in read_jsonl(args.m8b_artifacts / "truth-free.jsonl")}
    jobs = []
    for position, row in enumerate(selected.itertuples(index=False), 1):
        case_id = str(row.case)
        if case_id in done:
            continue
        metric_path = args.data_dir / case_id / "metrics.parquet"
        if not metric_path.exists():
            raise FileNotFoundError(metric_path)
        snapshot = m8b[case_id]["fault"]["features"] if bool(row.has_traces) else None
        jobs.append((position, case_id, str(row.dataset), str(row.system), int(row.inject_time), metric_path, snapshot))
    workers = max(1, int(os.environ.get("M9B_WORKERS", "4")))
    with path.open("a", encoding="utf-8") as output, ProcessPoolExecutor(max_workers=workers) as executor:
        for record in executor.map(_feature_job, jobs, chunksize=1):
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            output.flush()
            os.fsync(output.fileno())
            if record["position"] % 25 == 0 or record["position"] == 735:
                print(f"m9b features {record['position']}/735 {record['external_case_id']}", flush=True)
    records = read_jsonl(path)
    if len(records) != 735 or len({record["external_case_id"] for record in records}) != 735:
        raise ValueError("incomplete or duplicated M9B truth-free output")
    seal = {"schema": "m9b-v1", "records": 735, "sha256": sha256_file(path),
            "sealed_before_label_join": True, "m9a_base_commit": M9A_COMMIT}
    save_json(args.artifact_dir / "truth-free-seal.json", seal)
    return records, seal


def _feature_job(job: tuple) -> dict:
    position, case_id, dataset, system, inject_time, metric_path, snapshot = job
    features = extract_case_features(metric_path, inject_time, snapshot)
    return {"position": position, "external_case_id": case_id, "dataset": dataset, "system": system,
            "metric_sha256": sha256_file(metric_path), "features": features}


def join_labels(records: list[dict], index: pd.DataFrame, seal: dict) -> tuple[list[dict], list[dict]]:
    if not seal.get("sealed_before_label_join"):
        raise ValueError("labels require sealed truth-free M9B features")
    truth = {str(row.case): row for row in index.itertuples(index=False)}
    cases, rows = [], []
    for record in records:
        label = truth[record["external_case_id"]]
        root = normalize_root(str(label.root_cause_service), str(label.dataset))
        candidates = record["features"]["candidate_services"]
        root_observable = root in candidates
        eligible = root_observable and len(candidates) >= 2
        case = {"external_case_id": record["external_case_id"], "dataset": str(label.dataset),
                "system": str(label.system), "fault": str(label.fault), "root_service": root,
                "candidate_count": len(candidates), "root_observable": root_observable,
                "triggered_eligible": eligible, "mapping_coverage": record["features"]["mapping_coverage"],
                "audit": record["features"]["audit"]}
        cases.append(case)
        if eligible:
            for service in record["features"]["services"]:
                rows.append({"incident_id": record["external_case_id"], "dataset": str(label.dataset),
                             "system": str(label.system), "service": service["service"],
                             "label": int(service["service"] == root), **service["vector"]})
    return cases, rows


def metric_models(rows: list[dict], cases: list[dict], model_dir: Path) -> dict:
    ids = ids_by_dataset(cases)
    fold_results = {}
    tunings = []
    for name, train_sets, test_set in METRIC_SYSTEM_HOLDOUTS:
        train_ids = sum((ids[value] for value in train_sets), [])
        tuning = select_hyperparameters(rows, train_ids, METRIC_MODEL_COLUMNS, f"m9b-metric-{name}")
        selected = tuning["selected"]
        path = model_dir / "metric-holdouts" / f"train-{name.lower().replace('+', '-')}-test-{test_set.lower()}.json"
        model = fit_fixed(rows, train_ids, METRIC_MODEL_COLUMNS, selected["hyperparameters"],
                          selected["training_rounds"], path)
        metrics, _ = evaluate_model(model, rows, ids[test_set], METRIC_MODEL_COLUMNS)
        fold_results[name] = {"training_datasets": train_sets, "test_dataset": test_set,
                              "train_cases": len(train_ids), "test": metrics, "tuning": tuning,
                              "model_sha256": sha256_file(path)}
        tunings.append(tuning)
    final_hyperparameters, rounds = aggregate_tuning(tunings)
    re1_ids = sum((ids[value] for value in RE1), [])
    final_path = model_dir / "m9b-metric-lambdamart-v1.json"
    final = fit_fixed(rows, re1_ids, METRIC_MODEL_COLUMNS, final_hyperparameters, rounds, final_path)
    external_ids = sum((ids[value] for value in METRIC_EXTERNAL), [])
    external_metrics, external_rankings = evaluate_model(final, rows, external_ids, METRIC_MODEL_COLUMNS)
    by_dataset = {dataset: evaluate_model(final, rows, ids[dataset], METRIC_MODEL_COLUMNS)[0]
                  for dataset in METRIC_EXTERNAL}
    group_drop = metric_group_drop(rows, ids, final_hyperparameters, rounds)
    return {"version": "m9b-metric-lambdamart-v1", "system_holdout": fold_results,
            "frozen_hyperparameters": final_hyperparameters, "training_rounds": rounds,
            "final_training_cases": len(re1_ids), "model_sha256": sha256_file(final_path),
            "external": {"overall": external_metrics, "by_dataset": by_dataset,
                         "rankings": external_rankings}, "feature_group_ablation": group_drop}


def multisource_models(rows: list[dict], cases: list[dict], model_dir: Path, m8b_artifacts: Path,
                       metric_model_rankings: dict[str, list[dict]]) -> dict:
    ids = ids_by_dataset(cases)
    folds, all_rankings = {}, {}
    for name, train_set, test_sets in MULTISOURCE_FOLDS:
        tuning = select_hyperparameters(rows, ids[train_set], FEATURE_COLUMNS_M9B, f"m9b-multisource-{train_set}")
        selected = tuning["selected"]
        path = model_dir / "multisource-folds" / f"{name}.json"
        model = fit_fixed(rows, ids[train_set], FEATURE_COLUMNS_M9B, selected["hyperparameters"],
                          selected["training_rounds"], path)
        tests = {}
        for dataset in test_sets:
            metrics, rankings = evaluate_model(model, rows, ids[dataset], FEATURE_COLUMNS_M9B)
            tests[dataset] = metrics
            all_rankings.update(rankings)
        folds[name] = {"train_dataset": train_set, "train_cases": len(ids[train_set]), "tests": tests,
                       "tuning": tuning, "model_sha256": sha256_file(path), "model_path": str(path)}
    primary_ids = sum((ids[value] for value in MULTISOURCE), [])
    learned = metrics_from_combined(all_rankings, primary_ids)
    by_dataset = {dataset: metrics_from_combined(all_rankings, ids[dataset]) for dataset in MULTISOURCE}
    baselines, baseline_rankings = baseline_evaluation(rows, primary_ids)
    metric_model_primary = {incident: metric_model_rankings[incident]
                            for incident in primary_ids if incident in metric_model_rankings}
    baselines["m9b_metric_lambdamart"] = metrics_from_combined(metric_model_primary, primary_ids)
    baseline_rankings["m9b_metric_lambdamart"] = metric_model_primary
    baseline_by_dataset = {dataset: baseline_evaluation(rows, ids[dataset])[0] for dataset in MULTISOURCE}
    for dataset in MULTISOURCE:
        baseline_by_dataset[dataset]["m9b_metric_lambdamart"] = metrics_from_combined(
            metric_model_rankings, ids[dataset])
    ablation = modality_ablation(rows, ids, folds, MULTISOURCE_FOLDS)
    best_trace = max(("soft_topology_v1", "soft_trace_v1", "soft_hybrid_v1"),
                     key=lambda name: (baselines[name]["ac_at_1"], baselines[name]["mrr"], name))
    m9b_methods = {"m9b_multisource_lambdamart": (learned, all_rankings),
                   **{name: (baselines[name], baseline_rankings[name])
                      for name in ("metric_max_shift", "metric_top2", "rank_fusion_v1",
                                   "m9b_metric_lambdamart")}}
    best_m9b = max(m9b_methods, key=lambda name: (m9b_methods[name][0]["ac_at_1"],
                                                  m9b_methods[name][0]["mrr"], name))
    learned_ranks = truth_ranks(m9b_methods[best_m9b][1])
    trace_ranks = truth_ranks(baseline_rankings[best_trace])
    common = sorted(set(learned_ranks) & set(trace_ranks))
    paired = paired_bootstrap([learned_ranks[value] for value in common],
                              [trace_ranks[value] for value in common], resamples=2000, seed=SEED)
    autonomous = autonomous_metrics(cases, all_rankings, m8b_artifacts)
    return {"version": "m9b-multisource-lambdamart-v1", "folds": folds,
            "triggered": {"overall": learned, "by_dataset": by_dataset, "rankings": all_rankings},
            "baselines": baselines, "baseline_rankings": baseline_rankings,
            "baseline_by_dataset": baseline_by_dataset,
            "best_trace_only": best_trace, "best_m9b": best_m9b, "paired_vs_best_trace": paired,
            "modality_ablation": ablation, "autonomous_m5_trigger": autonomous}


def metric_group_drop(rows: list[dict], ids: dict[str, list[str]], hyperparameters: dict, rounds: int) -> dict:
    train_ids = sum((ids[value] for value in RE1), [])
    test_ids = sum((ids[value] for value in METRIC_EXTERNAL), [])
    result = {}
    for family in ("cpu", "memory", "disk_io", "socket", "workload", "latency_p50", "latency_p90"):
        columns = tuple(name for name in METRIC_MODEL_COLUMNS if not name.startswith(f"metric_{family}_"))
        model = fit_fixed(rows, train_ids, columns, hyperparameters, rounds)
        result[f"without_{family}"] = evaluate_model(model, rows, test_ids, columns)[0]
    return result


def modality_ablation(rows: list[dict], ids: dict[str, list[str]], folds: dict, fold_specs: tuple) -> dict:
    subsets = modality_subsets()
    result = {}
    for subset, columns in subsets.items():
        rankings = {}
        for name, train_set, test_sets in fold_specs:
            selected = folds[name]["tuning"]["selected"]
            model = fit_fixed(rows, ids[train_set], columns, selected["hyperparameters"],
                              selected["training_rounds"])
            for dataset in test_sets:
                _, predicted = evaluate_model(model, rows, ids[dataset], columns)
                rankings.update(predicted)
        result[subset] = {"columns": len(columns), **metrics_from_combined(rankings, list(rankings))}
    return result


def modality_subsets() -> dict[str, tuple[str, ...]]:
    return {
        "metrics_only": METRIC_MODEL_COLUMNS,
        "traces_only": TRACE_MODEL_COLUMNS,
        "topology_only": TOPOLOGY_COLUMNS,
        "metrics_traces": tuple(dict.fromkeys(METRIC_MODEL_COLUMNS + TRACE_MODEL_COLUMNS)),
        "metrics_topology": tuple(dict.fromkeys(METRIC_MODEL_COLUMNS + TOPOLOGY_COLUMNS)),
        "traces_topology": tuple(dict.fromkeys(TRACE_MODEL_COLUMNS + TOPOLOGY_COLUMNS)),
        "all": FEATURE_COLUMNS_M9B,
    }


def baseline_evaluation(rows: list[dict], incident_ids: list[str]) -> tuple[dict, dict]:
    selected = defaultdict(list)
    wanted = set(incident_ids)
    for row in rows:
        if row["incident_id"] in wanted:
            selected[row["incident_id"]].append(row)
    rankings = {name: {} for name in ("metric_max_shift", "metric_top2", "soft_topology_v1",
                                      "soft_trace_v1", "soft_hybrid_v1", "rank_fusion_v1")}
    for incident, group in selected.items():
        score_rows = {
            "metric_max_shift": [(row, row["metric_max_shift_score"]) for row in group],
            "metric_top2": [(row, row["metric_top2_score"]) for row in group],
            "soft_topology_v1": [(row, _topology_score(row)) for row in group],
            "soft_trace_v1": [(row, _trace_score(row)) for row in group],
        }
        local = {}
        for name, values in score_rows.items():
            local[name] = _ranking(values)
            rankings[name][incident] = local[name]
        local["soft_hybrid_v1"] = rank_fusion((local["soft_topology_v1"], local["soft_trace_v1"]))
        rankings["soft_hybrid_v1"][incident] = local["soft_hybrid_v1"]
        rankings["rank_fusion_v1"][incident] = rank_fusion((local["metric_max_shift"], local["soft_hybrid_v1"]))
    metrics = {name: metrics_from_combined(values, list(values)) for name, values in rankings.items()}
    sizes = [len(group) for group in selected.values()]
    metrics["chance"] = {
        "cases": len(sizes),
        "ac_at_1": float(np.mean([1 / size for size in sizes])),
        "ac_at_3": float(np.mean([min(3, size) / size for size in sizes])),
        "mrr": float(np.mean([sum(1 / rank for rank in range(1, size + 1)) / size for size in sizes])),
        "ndcg_at_1": float(np.mean([1 / size for size in sizes])),
        "ndcg_at_3": float(np.mean([sum(1 / math.log2(rank + 1) for rank in range(1, min(3, size) + 1)) / size
                                    for size in sizes])),
    }
    return metrics, rankings


def _topology_score(row: dict) -> float:
    return float(np.mean([row["trace_topology_f1_percentile"], row["trace_ancestor_ratio_percentile"],
                          row["trace_descendant_ratio_percentile"], row["trace_normalized_in_degree_percentile"]]))


def _trace_score(row: dict) -> float:
    return float(np.mean([row["trace_latency_z_log1p_percentile"], row["trace_error_z_log1p_percentile"],
                          row["trace_local_evidence_percentile"], row["trace_log1p_median_exclusive_duration_ms_percentile"],
                          row["trace_median_downstream_wait_ratio_percentile"]]))


def _ranking(values: list[tuple[dict, float]]) -> list[dict]:
    ranked = [{"service": row["service"], "score": float(score), "label": int(row["label"])} for row, score in values]
    return rank_scores(ranked)


def rank_scores(ranked: list[dict]) -> list[dict]:
    ranked.sort(key=lambda value: (-value["score"], value["service"]))
    for position, value in enumerate(ranked, 1):
        value["rank"] = position
    return ranked


def rank_fusion(modalities: tuple[list[dict], ...]) -> list[dict]:
    services = sorted({value["service"] for ranking in modalities for value in ranking})
    labels = {value["service"]: value["label"] for ranking in modalities for value in ranking}
    scores = defaultdict(list)
    for ranking in modalities:
        size = len(ranking)
        for value in ranking:
            scores[value["service"]].append(1.0 if size == 1 else 1 - (value["rank"] - 1) / (size - 1))
    return rank_scores([{"service": service, "score": float(np.mean(scores[service])), "label": labels[service]}
                        for service in services])


def ids_by_dataset(cases: list[dict]) -> dict[str, list[str]]:
    datasets = sorted({case["dataset"] for case in cases})
    return {dataset: sorted(case["external_case_id"] for case in cases
                            if case["dataset"] == dataset and case["triggered_eligible"])
            for dataset in datasets}


def aggregate_tuning(tunings: list[dict]) -> tuple[dict, int]:
    grouped = defaultdict(list)
    for tuning in tunings:
        for candidate in tuning["search"]:
            key = json.dumps(candidate["hyperparameters"], sort_keys=True)
            grouped[key].append(candidate)
    ordered = sorted(grouped.items(), key=lambda item: (
        -statistics.mean(value["validation"]["mrr"] for value in item[1]),
        -statistics.mean(value["validation"]["ac_at_1"] for value in item[1]), item[0]))
    key, values = ordered[0]
    return json.loads(key), max(1, round(statistics.median(value["training_rounds"] for value in values)))


def metrics_from_combined(rankings: dict[str, list[dict]], incident_ids: list[str]) -> dict:
    ranks = truth_ranks({incident: rankings[incident] for incident in incident_ids if incident in rankings})
    return {"cases": len(ranks), **rank_metrics(ranks.values())}


def autonomous_metrics(cases: list[dict], rankings: dict[str, list[dict]], m8b_artifacts: Path) -> dict:
    m8b_path = m8b_artifacts / "evaluation.json"
    m8b = json.loads(m8b_path.read_text())
    old = {case["external_case_id"]: case for case in m8b["cases"]}
    selected = [case for case in cases if case["dataset"] in MULTISOURCE]
    hits = 0
    for case in selected:
        prior = old[case["external_case_id"]]
        ranking = rankings.get(case["external_case_id"], [])
        rank = next((value["rank"] for value in ranking if value["label"] == 1), 0)
        hits += bool(prior["detected"] and rank == 1)
    overall = m8b["by_dataset"]["overall"]
    return {"cases": len(selected), "detection_recall": overall["detection_recall"],
            "healthy_fpr": overall["healthy_fpr"], "end_to_end_ac_at_1": hits / max(1, len(selected)),
            "detector": "frozen M5/v1", "historical_localization_eligible": overall["localization_eligible"],
            "historical_m6_m7_methods": overall["methods"]}


def coverage_summary(cases: list[dict]) -> dict:
    by_dataset = {}
    for dataset in sorted({case["dataset"] for case in cases}):
        values = [case for case in cases if case["dataset"] == dataset]
        by_dataset[dataset] = {
            "cases": len(values), "root_observable": sum(case["root_observable"] for case in values),
            "triggered_eligible": sum(case["triggered_eligible"] for case in values),
            "mean_candidates": float(np.mean([case["candidate_count"] for case in values])),
            "metric_entity_match_ratio": _ratio(sum(case["mapping_coverage"]["matched"] for case in values),
                                                 sum(case["mapping_coverage"]["entities"] for case in values)),
            "unmatched_infrastructure": sum(case["mapping_coverage"]["unmatched_infrastructure"] for case in values),
        }
    audits = [case["audit"] for case in cases]
    return {"cases": len(cases), "by_dataset": by_dataset,
            "metric_adapter": {"duplicate_timestamps": sum(value["duplicate_timestamps"] for value in audits),
                               "missing_timestamps": sum(value["missing_timestamps"] for value in audits),
                               "nan_values": sum(value["nan_values"] for value in audits),
                               "inf_values": sum(value["inf_values"] for value in audits),
                               "unknown_columns": sum(len(value["unknown_columns"]) for value in audits),
                               "cadence_seconds": dict(Counter(value["cadence_seconds_median"] for value in audits))}}


def verdict(result: dict) -> dict:
    study = result["multisource_study"]
    baseline = study["baselines"][study["best_trace_only"]]
    best_m9b = study["best_m9b"]
    learned = (study["triggered"]["overall"] if best_m9b == "m9b_multisource_lambdamart"
               else study["baselines"][best_m9b])
    paired = study["paired_vs_best_trace"]
    delta_ac1 = learned["ac_at_1"] - baseline["ac_at_1"]
    delta_mrr = learned["mrr"] - baseline["mrr"]
    gate = ("STRONG_MULTISOURCE_GAIN" if delta_ac1 >= .10 and paired["ac_at_1"]["ci_low"] > 0 else
            "PARTIAL_MULTISOURCE_GAIN" if delta_ac1 >= .05 or delta_mrr >= .05 else "NO_JUSTIFIED_GAIN")
    re3_multi = np.mean([
        (study["triggered"]["by_dataset"][name]["ac_at_1"] if best_m9b == "m9b_multisource_lambdamart"
         else study["baseline_by_dataset"][name][best_m9b]["ac_at_1"])
        for name in ("RE3-OB", "RE3-TT")])
    re3_trace = np.mean([study["baseline_by_dataset"][name][study["best_trace_only"]]["ac_at_1"]
                         for name in ("RE3-OB", "RE3-TT")])
    code_fault = "IMPROVED" if re3_multi - re3_trace >= .05 else ("UNCHANGED" if re3_multi >= re3_trace - .05 else "FAILED")
    recommendation = "KEEP MULTISOURCE LAMBDAMART" if gate == "STRONG_MULTISOURCE_GAIN" else (
        "ADD LOG MODALITY" if code_fault != "IMPROVED" else "INVESTIGATE GNN")
    return {"gate": gate, "best_m9b": best_m9b, "delta_ac_at_1": delta_ac1, "delta_mrr": delta_mrr,
            "code_fault_coverage": code_fault, "recommendation": recommendation,
            "locked_rule": "strong delta AC@1 >=0.10 and bootstrap lower >0; partial delta AC@1 >=0.05 or delta MRR >=0.05"}


def integrity_manifest(result: dict, args: argparse.Namespace) -> dict:
    models = sorted(args.model_dir.glob("**/*.json"))
    return {"experiment_version": EXPERIMENT_VERSION, "code_base_commit": M9A_COMMIT,
            "rcaeval_commit": RCAEVAL_REVISION, "hf_revision": HF_REVISION,
            "cases_index_sha256": INDEX_SHA256, "m7_sha256": M7_SHA256,
            "m9a_commit": M9A_COMMIT, "truth_free_sha256": result["truth_free_seal"]["sha256"],
            "feature_columns": FEATURE_COLUMNS_M9B,
            "model_sha256": {str(path.relative_to(args.model_dir)): sha256_file(path) for path in models
                             if path.name not in {"evaluation.json", "integrity_manifest.json"}},
            "python_version": platform.python_version(), "numpy_version": np.__version__,
            "xgboost_version": xgb.__version__, "seed": SEED,
            "training_scope": "RE1 metric development; RE2 cross-system multisource; RE3 evaluation only"}


def models_manifest(result: dict) -> dict:
    metric = result["metric_study"]
    multi = result["multisource_study"]
    entries = [{
        "model_version": metric["version"], "schema": "m9b-v1",
        "implementation_parent_commit": M9A_COMMIT, "training_suites": list(RE1),
        "test_suites": list(METRIC_EXTERNAL), "feature_columns": list(METRIC_MODEL_COLUMNS),
        "hyperparameters": metric["frozen_hyperparameters"], "iterations": metric["training_rounds"],
        "dataset_hashes": {"cases_index": INDEX_SHA256, "truth_free": result["truth_free_seal"]["sha256"]},
        "model_sha256": metric["model_sha256"],
    }]
    for name, value in multi["folds"].items():
        entries.append({
            "model_version": multi["version"], "fold": name, "schema": "m9b-v1",
            "implementation_parent_commit": M9A_COMMIT, "training_suites": [value["train_dataset"]],
            "test_suites": list(value["tests"]), "feature_columns": list(FEATURE_COLUMNS_M9B),
            "hyperparameters": value["tuning"]["selected"]["hyperparameters"],
            "iterations": value["tuning"]["selected"]["training_rounds"],
            "dataset_hashes": {"cases_index": INDEX_SHA256, "truth_free": result["truth_free_seal"]["sha256"]},
            "model_sha256": value["model_sha256"],
        })
    return {"python_version": platform.python_version(), "xgboost_version": xgb.__version__,
            "numpy_version": np.__version__, "seed": SEED, "models": entries}


def _compact(result: dict) -> dict:
    metric = result["metric_study"]
    multi = result["multisource_study"]
    compact_metric = {**metric, "external": {key: value for key, value in metric["external"].items() if key != "rankings"}}
    compact_multi = {key: value for key, value in multi.items() if key not in {"baseline_rankings"}}
    compact_multi["triggered"] = {key: value for key, value in multi["triggered"].items() if key != "rankings"}
    return {**result, "metric_study": compact_metric, "multisource_study": compact_multi}


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


# Report rendering is kept here so the committed report is generated from the
# exact evaluation object, not manually transcribed.
def render_reports(result: dict, cases: list[dict], rows: list[dict], docs: Path, model_dir: Path) -> None:
    from .m9b_report import render_all
    render_all(result, cases, rows, docs, model_dir)


if __name__ == "__main__":
    main()
